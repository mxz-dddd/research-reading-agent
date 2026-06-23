import base64
import hashlib
import hmac
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import app.core.database as database
from app.core.database import init_db
from app.schemas.agent import AgentQueryResponse, AgentToolCall
from app.services.feishu_service import FeishuService


def _payload(event_id: str = "evt_1", message_id: str = "msg_1") -> bytes:
    return json.dumps(
        {
            "schema": "2.0",
            "header": {
                "event_id": event_id,
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_1"}},
                "message": {
                    "message_id": message_id,
                    "chat_id": "oc_1",
                    "message_type": "text",
                    "content": json.dumps({"text": "查一下最近的 workflow"}, ensure_ascii=False),
                },
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _text_payload(
    text: str,
    *,
    event_id: str,
    message_id: str,
    chat_id: str = "oc_1",
    open_id: str = "ou_1",
    chat_type: str = "group",
    root_id: str | None = None,
    parent_id: str | None = None,
) -> bytes:
    message = {
        "message_id": message_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "message_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    if root_id:
        message["root_id"] = root_id
    if parent_id:
        message["parent_id"] = parent_id
    return json.dumps(
        {
            "schema": "2.0",
            "header": {"event_id": event_id, "event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": open_id}},
                "message": message,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _settings(**overrides):
    values = {
        "feishu_verification_token": None,
        "feishu_enable_signature_check": False,
        "feishu_encrypt_key": None,
        "feishu_app_id": None,
        "feishu_app_secret": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _non_text_payload(event_id: str = "evt_non_text", message_id: str = "msg_non_text") -> bytes:
    return json.dumps(
        {
            "schema": "2.0",
            "header": {
                "event_id": event_id,
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_1"}},
                "message": {
                    "message_id": message_id,
                    "chat_id": "oc_1",
                    "message_type": "image",
                    "content": json.dumps({"image_key": "img_1"}),
                },
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def test_feishu_challenge_returns_challenge() -> None:
    service = FeishuService()
    raw = json.dumps(
        {"type": "url_verification", "challenge": "abc", "token": None},
    ).encode("utf-8")

    assert service.handle_webhook(raw_body=raw, headers={}) == {"challenge": "abc"}


def test_feishu_wrong_verification_token_returns_401(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.feishu_service.settings",
        _settings(feishu_verification_token="expected-token"),
    )
    service = FeishuService()
    raw = json.dumps(
        {"type": "url_verification", "challenge": "abc", "token": "wrong-token"},
    ).encode("utf-8")

    with pytest.raises(HTTPException) as exc_info:
        service.handle_webhook(raw_body=raw, headers={})

    assert exc_info.value.status_code == 401


def test_feishu_invalid_json_returns_400() -> None:
    service = FeishuService()

    with pytest.raises(HTTPException) as exc_info:
        service.handle_webhook(raw_body=b"{not-json", headers={})

    assert exc_info.value.status_code == 400


def test_feishu_valid_signature_passes(monkeypatch) -> None:
    encrypt_key = "test-encrypt-key"
    timestamp = "1710000000"
    nonce = "nonce-1"
    raw_body = _payload(event_id="evt_signed", message_id="msg_signed")
    signature = hashlib.sha256(f"{timestamp}{nonce}{encrypt_key}".encode() + raw_body).hexdigest()
    monkeypatch.setattr(
        "app.services.feishu_service.settings",
        _settings(feishu_enable_signature_check=True, feishu_encrypt_key=encrypt_key),
    )
    service = FeishuService()
    monkeypatch.setattr(service, "_process_message_event", lambda *args, **kwargs: None)

    result = service.handle_webhook(
        raw_body=raw_body,
        headers={
            "x-lark-request-timestamp": timestamp,
            "x-lark-request-nonce": nonce,
            "x-lark-signature": signature,
        },
    )

    assert result["event_id"] == "evt_signed"


@pytest.mark.parametrize("signature", ["wrong-signature", ""])
def test_feishu_invalid_or_missing_signature_is_rejected(monkeypatch, signature: str) -> None:
    monkeypatch.setattr(
        "app.services.feishu_service.settings",
        _settings(feishu_enable_signature_check=True, feishu_encrypt_key="test-encrypt-key"),
    )
    headers = {
        "x-lark-request-timestamp": "1710000000",
        "x-lark-request-nonce": "nonce-1",
    }
    if signature:
        headers["x-lark-signature"] = signature

    with pytest.raises(HTTPException) as exc_info:
        FeishuService().handle_webhook(raw_body=_payload(), headers=headers)

    assert exc_info.value.status_code == 401


def test_feishu_legacy_hmac_base64_signature_is_rejected(monkeypatch) -> None:
    encrypt_key = "test-encrypt-key"
    timestamp = "1710000000"
    nonce = "nonce-1"
    raw_body = _payload()
    signed_content = f"{timestamp}{nonce}{encrypt_key}".encode() + raw_body
    legacy_signature = base64.b64encode(
        hmac.new(encrypt_key.encode("utf-8"), signed_content, hashlib.sha256).digest()
    ).decode("utf-8")
    monkeypatch.setattr(
        "app.services.feishu_service.settings",
        _settings(feishu_enable_signature_check=True, feishu_encrypt_key=encrypt_key),
    )

    with pytest.raises(HTTPException) as exc_info:
        FeishuService().handle_webhook(
            raw_body=raw_body,
            headers={
                "x-lark-request-timestamp": timestamp,
                "x-lark-request-nonce": nonce,
                "x-lark-signature": legacy_signature,
            },
        )

    assert exc_info.value.status_code == 401


def test_feishu_signature_check_disabled_accepts_unsigned_event(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.feishu_service.settings",
        _settings(feishu_enable_signature_check=False),
    )
    service = FeishuService()
    monkeypatch.setattr(service, "_process_message_event", lambda *args, **kwargs: None)

    result = service.handle_webhook(raw_body=_payload(), headers={})

    assert result["event_id"] == "evt_1"


def test_feishu_signature_check_requires_encrypt_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.feishu_service.settings",
        _settings(feishu_enable_signature_check=True, feishu_encrypt_key=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        FeishuService().handle_webhook(raw_body=_payload(), headers={})

    assert exc_info.value.status_code == 500


def test_feishu_non_text_message_replies_without_agent(monkeypatch) -> None:
    service = FeishuService()
    replies: list[tuple[str | None, str]] = []
    agent_calls: list[str] = []

    monkeypatch.setattr(
        service.agent_service, "query", lambda request: agent_calls.append(request.text)
    )
    monkeypatch.setattr(
        service,
        "_reply_to_feishu",
        lambda message_id, text, **kwargs: replies.append((message_id, text)) or {"success": True},
    )

    result = service.handle_webhook(raw_body=_non_text_payload(), headers={})

    assert result["message"] == "飞书事件已接收并处理"
    assert replies[0][0] == "msg_non_text"
    assert "只支持文本消息" in replies[0][1]
    assert agent_calls == []


def test_feishu_text_event_is_queued_and_deduped(monkeypatch) -> None:
    service = FeishuService()
    replies: list[tuple[str | None, str]] = []

    monkeypatch.setattr(
        service.agent_service,
        "query",
        lambda request: SimpleNamespace(
            model_dump=lambda: {
                "final_answer": f"ok:{request.text}",
                "chosen_tool": "get_latest_workflow",
                "routing_method": "fallback",
            }
        ),
    )
    monkeypatch.setattr(
        service,
        "_reply_to_feishu",
        lambda message_id, text, **kwargs: replies.append((message_id, text)) or {"success": True},
    )

    background = BackgroundTasks()
    first = service.handle_webhook(raw_body=_payload(), headers={}, background_tasks=background)
    second = service.handle_webhook(
        raw_body=_payload(), headers={}, background_tasks=BackgroundTasks()
    )

    assert first["message"] == "飞书事件已接收，后台处理中"
    assert second["message"] == "duplicate event ignored"
    assert len(background.tasks) == 1

    task = background.tasks[0]
    task.func(*task.args, **task.kwargs)

    assert replies
    assert replies[0][0] == "msg_1"
    assert "ok:查一下最近的 workflow" in replies[0][1]
    assert "已调用工具" not in replies[0][1]
    assert "路由方式" not in replies[0][1]


def test_feishu_duplicate_message_id_without_event_id_is_not_processed_twice(monkeypatch) -> None:
    service = FeishuService()
    calls: list[str] = []
    replies: list[tuple[str | None, str]] = []
    raw_payload = json.loads(_payload(event_id="evt_ignored", message_id="msg_dup").decode("utf-8"))
    raw_payload["header"].pop("event_id")
    raw = json.dumps(raw_payload, ensure_ascii=False).encode("utf-8")

    monkeypatch.setattr(
        service.agent_service,
        "query",
        lambda request: (
            calls.append(request.text)
            or SimpleNamespace(
                model_dump=lambda: {
                    "final_answer": "ok",
                    "chosen_tool": "get_latest_workflow",
                    "routing_method": "fallback",
                }
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_reply_to_feishu",
        lambda message_id, text, **kwargs: replies.append((message_id, text)) or {"success": True},
    )

    first = service.handle_webhook(raw_body=raw, headers={})
    second = service.handle_webhook(raw_body=raw, headers={})

    assert first["message"] == "飞书事件已接收并处理"
    assert second["message"] == "duplicate event ignored"
    assert calls == ["查一下最近的 workflow"]
    assert len(replies) == 1


def test_feishu_background_task_exception_is_logged(monkeypatch, caplog) -> None:
    service = FeishuService()

    def fail_inner(message):
        raise RuntimeError("simulated background failure")

    monkeypatch.setattr(service, "_process_message_event_inner", fail_inner)

    with caplog.at_level(logging.ERROR):
        service._process_message_event({"message_id": "msg_fail"})

    assert "Feishu background processing failed" in caplog.text
    assert "msg_fail" in caplog.text


def test_feishu_logs_background_agent_and_reply_without_message_text(monkeypatch, caplog) -> None:
    service = FeishuService()
    replies: list[tuple[str | None, str]] = []

    monkeypatch.setattr(
        service.agent_service,
        "query",
        lambda request: SimpleNamespace(
            model_dump=lambda: {
                "success": True,
                "final_answer": f"ok:{request.text}",
                "chosen_tool": "get_latest_workflow",
                "routing_method": "fallback",
            }
        ),
    )
    monkeypatch.setattr(
        service,
        "_reply_to_feishu",
        lambda message_id, text, **kwargs: replies.append((message_id, text)) or {"success": True},
    )

    background = BackgroundTasks()
    with caplog.at_level(logging.INFO):
        result = service.handle_webhook(
            raw_body=_payload(event_id="evt_log", message_id="msg_log"),
            headers={},
            background_tasks=background,
        )
        task = background.tasks[0]
        task.func(*task.args, **task.kwargs)

    assert result["message"] == "飞书事件已接收，后台处理中"
    assert "webhook_received" in caplog.text
    assert "new_event" in caplog.text
    assert "background_task_started" in caplog.text
    assert "agent_query_started" in caplog.text
    assert "agent_query_completed" in caplog.text
    assert "feishu_reply_started" in caplog.text
    assert "feishu_reply_success" in caplog.text
    assert "msg_log" in caplog.text
    assert "evt_log" in caplog.text
    assert "查一下最近的 workflow" not in caplog.text


def test_feishu_logs_ignored_event_type(caplog) -> None:
    service = FeishuService()
    raw = json.dumps(
        {
            "schema": "2.0",
            "header": {"event_id": "evt_ignored_type", "event_type": "app.ticket.v1"},
            "event": {},
        },
        ensure_ascii=False,
    ).encode("utf-8")

    with caplog.at_level(logging.INFO):
        result = service.handle_webhook(
            raw_body=raw, headers={}, background_tasks=BackgroundTasks()
        )

    assert result["event_type"] == "app.ticket.v1"
    assert "ignored_event_type" in caplog.text
    assert "app.ticket.v1" in caplog.text


def test_feishu_reply_http_failure_logs_status_code_and_feishu_error(monkeypatch, caplog) -> None:
    import io
    import urllib.error

    import app.services.feishu_service as feishu_module

    service = FeishuService()
    monkeypatch.setattr(service, "_tenant_access_token", lambda: "fake-token")

    def fail_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://open.feishu.cn/open-apis/im/v1/messages/msg_fail/reply",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(json.dumps({"code": 19001, "msg": "bad message"}).encode("utf-8")),
        )

    monkeypatch.setattr(feishu_module, "urlopen", fail_urlopen)

    with caplog.at_level(logging.ERROR):
        result = service._reply_to_feishu(
            "msg_fail",
            "reply text should not appear in logs",
            context={"event_id": "evt_fail", "message_id": "msg_fail", "message_type": "text"},
        )

    assert result["success"] is False
    assert "feishu_reply_failed" in caplog.text
    assert "400" in caplog.text
    assert "19001" in caplog.text
    assert "bad message" in caplog.text
    assert "fake-token" not in caplog.text
    assert "reply text should not appear in logs" not in caplog.text


def test_feishu_session_id_is_isolated_by_chat_user_and_thread() -> None:
    service = FeishuService()

    assert (
        service._conversation_session_id({"chat_id": "c1", "open_id": "u1", "chat_type": "p2p"})
        == "feishu:p2p:c1"
    )
    assert (
        service._conversation_session_id({"chat_id": "c1", "open_id": "u1", "chat_type": "group"})
        == "feishu:group:c1:u1"
    )
    assert (
        service._conversation_session_id({"chat_id": "c1", "open_id": "u2", "chat_type": "group"})
        == "feishu:group:c1:u2"
    )
    assert (
        service._conversation_session_id(
            {"chat_id": "c1", "open_id": "u1", "chat_type": "group", "root_id": "r1"}
        )
        == "feishu:group:c1:r1:u1"
    )


def test_feishu_followup_time_range_reuses_previous_search(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        database, "settings", SimpleNamespace(database_path=str(tmp_path / "feishu_context.db"))
    )
    init_db()
    service = FeishuService()
    replies: list[str] = []
    captured_followup: dict[str, object] = {}

    def fake_query(request):
        return AgentQueryResponse(
            success=True,
            intent="search_papers",
            chosen_tool="search_papers",
            tool_calls=[
                AgentToolCall(
                    tool_name="search_papers",
                    arguments={"topic": "VLF传播时延", "max_results": 5},
                    success=True,
                )
            ],
            final_answer="找到 5 篇相关论文",
            data=[
                {"id": 101, "title": "Paper 1", "url": "https://arxiv.org/abs/1"},
                {"id": 102, "title": "Paper 2", "url": "https://arxiv.org/abs/2"},
            ],
            routing_method="fallback",
        )

    def fake_query_with_route(
        request, *, tool_name, arguments, intent=None, routing_method="context"
    ):
        captured_followup.update(arguments)
        return AgentQueryResponse(
            success=True,
            intent=tool_name,
            chosen_tool=tool_name,
            tool_calls=[AgentToolCall(tool_name=tool_name, arguments=arguments, success=True)],
            final_answer="找到 5 篇近十年的相关论文",
            data=[
                {"id": 201, "title": "Paper A", "url": "https://arxiv.org/abs/a"},
            ],
            routing_method=routing_method,
        )

    monkeypatch.setattr(service.agent_service, "query", fake_query)
    monkeypatch.setattr(service.agent_service, "query_with_route", fake_query_with_route)
    monkeypatch.setattr(
        service,
        "_reply_to_feishu",
        lambda message_id, text, **kwargs: replies.append(text) or {"success": True},
    )

    first = service.handle_webhook(
        raw_body=_text_payload(
            "帮我搜索5篇VLF传播时延相关论文", event_id="evt_ctx_1", message_id="msg_ctx_1"
        ),
        headers={},
    )
    second = service.handle_webhook(
        raw_body=_text_payload("要近十年的", event_id="evt_ctx_2", message_id="msg_ctx_2"),
        headers={},
    )

    assert first["message"] == "飞书事件已接收并处理"
    assert second["message"] == "飞书事件已接收并处理"
    assert captured_followup["topic"] == "VLF传播时延"
    assert captured_followup["max_results"] == 5
    assert captured_followup["published_from"]
    assert captured_followup["published_to"]
    assert "帮助" not in replies[-1]
    assert "followup_detected" not in replies[-1]
    assert "routing_method" not in replies[-1]


def test_feishu_append_search_excludes_previous_and_keeps_global_ordinals(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        database, "settings", SimpleNamespace(database_path=str(tmp_path / "feishu_append.db"))
    )
    init_db()
    service = FeishuService()
    routed_calls: list[tuple[str, dict[str, object]]] = []

    first_batch = [
        {"id": 100 + index, "title": f"Paper {index}", "url": f"https://arxiv.org/abs/{index}"}
        for index in range(1, 6)
    ]
    second_batch = [
        {"id": 100 + index, "title": f"Paper {index}", "url": f"https://arxiv.org/abs/{index}"}
        for index in range(6, 11)
    ]

    def fake_query(request):
        return AgentQueryResponse(
            success=True,
            intent="search_papers",
            chosen_tool="search_papers",
            tool_calls=[
                AgentToolCall(
                    tool_name="search_papers",
                    arguments={"topic": "VLF传播时延", "max_results": 5},
                    success=True,
                )
            ],
            final_answer="first",
            data=first_batch,
            routing_method="fallback",
        )

    def fake_query_with_route(
        request, *, tool_name, arguments, intent=None, routing_method="context"
    ):
        routed_calls.append((tool_name, dict(arguments)))
        if tool_name == "search_papers":
            data = second_batch
            answer = (
                "继续为你补充 5 篇：\n6. Paper 6\n7. Paper 7\n8. Paper 8\n9. Paper 9\n10. Paper 10"
            )
        else:
            paper_id = int(arguments["paper_id"])
            data = {"id": paper_id, "title": f"Paper {paper_id - 100}"}
            answer = "ok"
        return AgentQueryResponse(
            success=True,
            intent=tool_name,
            chosen_tool=tool_name,
            tool_calls=[AgentToolCall(tool_name=tool_name, arguments=arguments, success=True)],
            final_answer=answer,
            data=data,
            routing_method=routing_method,
        )

    monkeypatch.setattr(service.agent_service, "query", fake_query)
    monkeypatch.setattr(service.agent_service, "query_with_route", fake_query_with_route)
    monkeypatch.setattr(service, "_reply_to_feishu", lambda *args, **kwargs: {"success": True})

    service.handle_webhook(
        raw_body=_text_payload(
            "帮我搜索5篇VLF传播时延相关论文", event_id="evt_a1", message_id="msg_a1"
        ),
        headers={},
    )
    service.handle_webhook(
        raw_body=_text_payload("再来5篇", event_id="evt_a2", message_id="msg_a2"), headers={}
    )

    search_args = routed_calls[0][1]
    assert search_args["topic"] == "VLF传播时延"
    assert search_args["max_results"] == 5
    assert search_args["append_mode"] is True
    assert search_args["exclude_paper_ids"] == [101, 102, 103, 104, 105]
    assert search_args["exclude_urls"] == [
        f"https://arxiv.org/abs/{index}" for index in range(1, 6)
    ]

    session_id = service._conversation_session_id(
        {"chat_id": "oc_1", "open_id": "ou_1", "chat_type": "group"}
    )
    state = service.context_service.get_state(session_id)
    assert state is not None
    assert len(state.last_result_refs) == 10
    assert state.last_result_refs[6]["paper_id"] == 107

    service.handle_webhook(
        raw_body=_text_payload("第7篇", event_id="evt_a3", message_id="msg_a3"), headers={}
    )
    service.handle_webhook(
        raw_body=_text_payload("接收第8篇", event_id="evt_a4", message_id="msg_a4"), headers={}
    )

    assert routed_calls[1] == ("get_paper_detail", {"paper_id": 107})
    assert routed_calls[2] == ("accept_paper", {"paper_id": 108})


def test_feishu_batch_ingest_uses_previous_five_and_hides_internal_names(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        database, "settings", SimpleNamespace(database_path=str(tmp_path / "feishu_batch.db"))
    )
    init_db()
    service = FeishuService()
    replies: list[str] = []
    routed: dict[str, object] = {}
    papers = [
        {"id": 100 + index, "title": f"Paper {index}", "url": f"https://arxiv.org/abs/{index}"}
        for index in range(1, 6)
    ]

    monkeypatch.setattr(
        service.agent_service,
        "query",
        lambda request: AgentQueryResponse(
            success=True,
            intent="search_papers",
            chosen_tool="search_papers",
            tool_calls=[
                AgentToolCall(
                    tool_name="search_papers",
                    arguments={"topic": "VLF", "max_results": 5},
                    success=True,
                )
            ],
            final_answer="found",
            data=papers,
        ),
    )

    def fake_batch(request, *, tool_name, arguments, intent=None, routing_method="context"):
        routed.update({"tool_name": tool_name, "arguments": arguments})
        return AgentQueryResponse(
            success=True,
            intent=tool_name,
            chosen_tool=tool_name,
            tool_calls=[AgentToolCall(tool_name=tool_name, arguments=arguments, success=True)],
            final_answer="已完成对刚才 5 篇论文的深入阅读：\n1. Paper 1\n   状态：完成",
            data={
                "total": 5,
                "succeeded": 5,
                "failed": 0,
                "items": [
                    {
                        "position": index,
                        "paper_id": 100 + index,
                        "title": f"Paper {index}",
                        "status": "success",
                    }
                    for index in range(1, 6)
                ],
            },
            routing_method=routing_method,
        )

    monkeypatch.setattr(service.agent_service, "query_with_route", fake_batch)
    monkeypatch.setattr(
        service,
        "_reply_to_feishu",
        lambda message_id, text, **kwargs: replies.append(text) or {"success": True},
    )

    service.handle_webhook(
        raw_body=_text_payload("帮我搜索5篇VLF论文", event_id="evt_b1", message_id="msg_b1"),
        headers={},
    )
    service.handle_webhook(
        raw_body=_text_payload("对这五篇都进行深入阅读", event_id="evt_b2", message_id="msg_b2"),
        headers={},
    )

    assert routed["tool_name"] == "batch_ingest_papers"
    assert routed["arguments"] == {
        "paper_ids": [101, 102, 103, 104, 105],
        "source_positions": [1, 2, 3, 4, 5],
    }
    for internal in (
        "batch_ingest_papers",
        "ingest_paper",
        "read_papers",
        "paper_ids",
        "routing_method",
        "chosen_tool",
    ):
        assert internal not in replies[-1]

    session_id = service._conversation_session_id(
        {"chat_id": "oc_1", "open_id": "ou_1", "chat_type": "group"}
    )
    state = service.context_service.get_state(session_id)
    assert state is not None
    assert len(state.last_result_refs) == 5
