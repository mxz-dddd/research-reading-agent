import hashlib
import hmac
import json
import logging
import ssl
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from fastapi import BackgroundTasks, HTTPException

from app.core.config import settings
from app.schemas.agent import AgentQueryRequest
from app.services.agent_service import AgentService
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_followup_service import ConversationFollowupService

logger = logging.getLogger(__name__)


class FeishuService:
    def __init__(self) -> None:
        self.agent_service = AgentService()
        self.context_service = ConversationContextService()
        self.followup_service = ConversationFollowupService()
        self._seen_event_ids: set[str] = set()
        self._seen_lock = threading.Lock()

    def handle_webhook(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        background_tasks: BackgroundTasks | None = None,
    ) -> dict[str, Any]:
        payload = self._load_payload(raw_body)
        is_challenge = self._is_challenge(payload)
        event_type = self._event_type(payload)
        message = self._extract_message(payload) if not is_challenge else {}
        context = self._event_context(payload, message)
        self._log_event(
            "webhook_received",
            **context,
            is_challenge=is_challenge,
        )

        if is_challenge:
            self._verify_token(payload, context=context)
            return {"challenge": payload["challenge"]}

        self._verify_token(payload, context=context)
        self._verify_signature_if_needed(raw_body, headers, context=context)

        if event_type != "im.message.receive_v1":
            self._log_event(
                "ignored_event_type",
                **context,
                ignored_event_type=event_type,
            )
            return {
                "message": "已收到飞书事件，但当前只处理文本消息事件。",
                "event_type": event_type,
            }

        dedupe_id = self._dedupe_id(payload, message)
        dedupe_key = self._dedupe_key(payload, message)
        if dedupe_id and self._is_duplicate(dedupe_id):
            self._log_event(
                "duplicate_event",
                **context,
                dedupe_id=dedupe_id,
                dedupe_key=dedupe_key,
            )
            return {"message": "duplicate event ignored", "event_id": dedupe_id}

        self._log_event(
            "new_event",
            **context,
            dedupe_id=dedupe_id,
            dedupe_key=dedupe_key,
        )

        if background_tasks is not None:
            background_tasks.add_task(self._process_message_event, message, context)
            self._log_event("background_task_scheduled", **context)
            return {"message": "飞书事件已接收，后台处理中", "event_id": dedupe_id}

        self._process_message_event(message, context)
        return {"message": "飞书事件已接收并处理", "event_id": dedupe_id}

    def _process_message_event(
        self,
        message: dict[str, str | None],
        context: dict[str, Any] | None = None,
    ) -> None:
        context = context or self._message_context(message)
        self._log_event("background_task_started", **context)
        try:
            self._process_message_event_inner(message, context)
        except Exception as exc:  # noqa: BLE001 - background task must never crash silently
            self._log_event(
                "background_task_failed",
                level="exception",
                **context,
                error_type=type(exc).__name__,
            )
            logger.exception(
                "Feishu background processing failed (message_id=%s): %s",
                message.get("message_id"),
                exc,
            )

    def _process_message_event_inner(
        self,
        message: dict[str, str | None],
        context: dict[str, Any],
    ) -> None:
        if message.get("message_type") != "text":
            final_answer = "我目前只支持文本消息。请直接发送研究方向、论文编号或操作请求。"
            self._send_reply_with_logging(message.get("message_id"), final_answer, context)
            return

        if not message.get("text"):
            final_answer = "我没有读到有效文本，请重新发送你的问题。"
            self._send_reply_with_logging(message.get("message_id"), final_answer, context)
            return

        self._log_event("agent_query_started", **context)
        session_id = self._conversation_session_id(message)
        user_id = f"feishu:{message.get('open_id') or message.get('chat_id')}"
        thread_id = message.get("root_id") or message.get("parent_id")
        try:
            with self.context_service.session_lock(session_id):
                state = self.context_service.get_state(session_id)
                turns = self.context_service.recent_turns(session_id, limit=6)
                resolution = self.followup_service.resolve(
                    message["text"],
                    state,
                    recent_turns=turns,
                )
                self._log_event(
                    "conversation_followup_resolved",
                    **context,
                    session_hash=self.context_service.session_hash(session_id),
                    followup_detected=resolution.is_followup,
                    context_hit=state is not None,
                    last_tool=state.last_tool if state else None,
                    resolved_tool=resolution.tool_name,
                    confidence=resolution.confidence,
                    reason=resolution.reason,
                )
                if resolution.clear_context:
                    self.context_service.clear_session(session_id)
                    final_answer = resolution.resolved_message
                    self._send_reply_with_logging(message.get("message_id"), final_answer, context)
                    return

                if resolution.direct_reply:
                    self.context_service.save_user_turn(
                        session_id=session_id,
                        message=message["text"],
                        message_id=message.get("message_id"),
                    )
                    self.context_service.save_assistant_turn(
                        session_id=session_id,
                        content=resolution.resolved_message,
                    )
                    self._send_reply_with_logging(
                        message.get("message_id"),
                        resolution.resolved_message,
                        context,
                    )
                    return

                self.context_service.save_user_turn(
                    session_id=session_id,
                    message=message["text"],
                    message_id=message.get("message_id"),
                )
                payload = AgentQueryRequest(
                    user_id=user_id,
                    session_id=session_id,
                    message=resolution.resolved_message if resolution.is_followup else message["text"],
                )
                if resolution.is_followup and resolution.tool_name:
                    agent_response = self.agent_service.query_with_route(
                        payload,
                        tool_name=resolution.tool_name,
                        arguments=resolution.arguments,
                        intent=resolution.intent,
                        routing_method="context",
                    )
                else:
                    agent_response = self.agent_service.query(payload)
                reply_text = self._format_agent_reply(agent_response.model_dump())
                if hasattr(agent_response, "success") and hasattr(agent_response, "tool_calls"):
                    self.context_service.update_from_agent_response(
                        session_id=session_id,
                        channel="feishu",
                        chat_id=message.get("chat_id"),
                        user_id=message.get("open_id"),
                        thread_id=thread_id,
                        user_message=message["text"],
                        assistant_text=reply_text,
                        response=agent_response,
                        previous_state=state,
                    )
            response_data = agent_response.model_dump()
            self._log_event(
                "agent_query_completed",
                **context,
                success=response_data.get("success"),
                chosen_tool=response_data.get("chosen_tool"),
                routing_method=response_data.get("routing_method"),
                state_updated=True,
            )
        except Exception as exc:
            self._log_event(
                "agent_query_failed",
                level="exception",
                **context,
                error_type=type(exc).__name__,
            )
            raise

        self._send_reply_with_logging(message.get("message_id"), reply_text, context)

    def _send_reply_with_logging(
        self,
        message_id: str | None,
        text: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        self._log_event("feishu_reply_started", **context)
        result = self._reply_to_feishu(message_id, text, context=context)
        if result.get("success"):
            self._log_event("feishu_reply_success", **context)
        else:
            self._log_event(
                "feishu_reply_failed",
                **context,
                error_type=type(result.get("error")).__name__,
            )
        return result

    def _load_payload(self, raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._log_event("webhook_invalid_json", error_type=type(exc).__name__)
            raise HTTPException(status_code=400, detail=f"飞书请求体不是合法 JSON：{exc}") from exc

        if "encrypt" in payload:
            self._log_event("webhook_encrypted_event_rejected")
            raise HTTPException(status_code=400, detail="当前暂不支持飞书加密事件，请先关闭事件加密。")
        return payload

    def _is_challenge(self, payload: dict[str, Any]) -> bool:
        return payload.get("type") == "url_verification" and "challenge" in payload

    def _verify_token(self, payload: dict[str, Any], *, context: dict[str, Any] | None = None) -> None:
        expected = settings.feishu_verification_token
        context = context or self._event_context(payload, {})
        if not expected:
            self._log_event("token_verification_skipped", **context, reason="not_configured")
            logger.warning("FEISHU_VERIFICATION_TOKEN 未配置，已跳过 token 校验。")
            return

        token = payload.get("token") or payload.get("header", {}).get("token")
        if token != expected:
            self._log_event("token_verification_failed", level="warning", **context)
            raise HTTPException(status_code=401, detail="飞书 verification token 校验失败")
        self._log_event("token_verification_success", **context)

    def _verify_signature_if_needed(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        context = context or {}
        if not settings.feishu_enable_signature_check:
            self._log_event("signature_verification_skipped", **context, reason="disabled")
            logger.warning(
                "飞书签名校验未启用，正在处理未验签事件；"
                "生产环境请设置 FEISHU_ENABLE_SIGNATURE_CHECK=true 并配置 FEISHU_ENCRYPT_KEY。"
            )
            return
        if not settings.feishu_encrypt_key:
            self._log_event("signature_verification_failed", level="warning", **context, reason="missing_encrypt_key")
            raise HTTPException(status_code=500, detail="已启用飞书签名校验，但缺少 FEISHU_ENCRYPT_KEY")

        timestamp = headers.get("x-lark-request-timestamp") or headers.get("x-feishu-request-timestamp")
        nonce = headers.get("x-lark-request-nonce") or headers.get("x-feishu-request-nonce")
        signature = headers.get("x-lark-signature") or headers.get("x-feishu-signature")
        if not timestamp or not nonce or not signature:
            self._log_event("signature_verification_failed", level="warning", **context, reason="missing_headers")
            raise HTTPException(status_code=401, detail="飞书签名请求头不完整")

        signed_content = (
            f"{timestamp}{nonce}{settings.feishu_encrypt_key}".encode("utf-8")
            + raw_body
        )
        expected = hashlib.sha256(signed_content).hexdigest()
        if not hmac.compare_digest(expected, signature):
            self._log_event("signature_verification_failed", level="warning", **context, reason="signature_mismatch")
            raise HTTPException(status_code=401, detail="飞书签名校验失败")
        self._log_event("signature_verification_success", **context)

    def _event_type(self, payload: dict[str, Any]) -> str | None:
        return payload.get("header", {}).get("event_type") or payload.get("event", {}).get("type")

    def _dedupe_id(self, payload: dict[str, Any], message: dict[str, str | None]) -> str | None:
        header = payload.get("header", {})
        return (
            header.get("event_id")
            or payload.get("uuid")
            or payload.get("event_id")
            or message.get("message_id")
        )

    def _dedupe_key(self, payload: dict[str, Any], message: dict[str, str | None]) -> str | None:
        header = payload.get("header", {})
        if header.get("event_id"):
            return "event_id"
        if payload.get("uuid"):
            return "uuid"
        if payload.get("event_id"):
            return "event_id"
        if message.get("message_id"):
            return "message_id"
        return None

    def _is_duplicate(self, dedupe_id: str) -> bool:
        with self._seen_lock:
            if dedupe_id in self._seen_event_ids:
                return True
            self._seen_event_ids.add(dedupe_id)
            if len(self._seen_event_ids) > 1000:
                self._seen_event_ids = set(list(self._seen_event_ids)[-500:])
            return False

    def _extract_message(self, payload: dict[str, Any]) -> dict[str, str | None]:
        event = payload.get("event", {})
        sender_id = event.get("sender", {}).get("sender_id", {})
        message = event.get("message", {})
        content = message.get("content") or "{}"
        try:
            content_data = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            content_data = {}

        return {
            "open_id": sender_id.get("open_id"),
            "chat_id": message.get("chat_id"),
            "message_id": message.get("message_id"),
            "root_id": message.get("root_id"),
            "parent_id": message.get("parent_id"),
            "chat_type": message.get("chat_type"),
            "message_type": message.get("message_type"),
            "text": (content_data.get("text") or "").strip(),
        }

    def _event_context(
        self,
        payload: dict[str, Any],
        message: dict[str, str | None],
    ) -> dict[str, Any]:
        header = payload.get("header", {})
        return {
            "event_type": self._event_type(payload),
            "event_id": header.get("event_id") or payload.get("event_id") or payload.get("uuid"),
            "message_id": message.get("message_id"),
            "message_type": message.get("message_type"),
            "chat_id": message.get("chat_id"),
            "open_id": message.get("open_id"),
            "root_id": message.get("root_id"),
            "parent_id": message.get("parent_id"),
            "chat_type": message.get("chat_type"),
        }

    def _message_context(self, message: dict[str, str | None]) -> dict[str, Any]:
        return {
            "event_type": None,
            "event_id": None,
            "message_id": message.get("message_id"),
            "message_type": message.get("message_type"),
        }

    def _conversation_session_id(self, message: dict[str, str | None]) -> str:
        chat_id = message.get("chat_id") or "unknown_chat"
        open_id = message.get("open_id") or "unknown_user"
        chat_type = (message.get("chat_type") or "").lower()
        thread_id = message.get("root_id") or message.get("parent_id")
        if chat_type in {"p2p", "private"}:
            return f"feishu:p2p:{chat_id}"
        if thread_id:
            return f"feishu:group:{chat_id}:{thread_id}:{open_id}"
        return f"feishu:group:{chat_id}:{open_id}"

    def _tenant_access_token(self) -> str:
        if not settings.feishu_app_id or not settings.feishu_app_secret:
            raise RuntimeError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET，无法获取 tenant_access_token")

        body = json.dumps(
            {
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            }
        ).encode("utf-8")
        request = Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20, context=self._ssl_context()) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败：code={data.get('code')} msg={data.get('msg')}")
        return data["tenant_access_token"]

    def _reply_to_feishu(
        self,
        message_id: str | None,
        text: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {"message_id": message_id}
        if not message_id:
            self._log_event("feishu_reply_failed", level="warning", **context, reason="missing_message_id")
            return {"success": False, "error": "缺少 message_id，无法回复飞书消息"}

        try:
            token = self._tenant_access_token()
            body = json.dumps(
                {
                    "msg_type": "text",
                    "content": json.dumps({"text": self._truncate_text(text)}, ensure_ascii=False),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            request = Request(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
                data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(request, timeout=20, context=self._ssl_context()) as response:
                http_status = getattr(response, "status", 200)
                data = json.loads(response.read().decode("utf-8"))
            if data.get("code") != 0:
                self._log_event(
                    "feishu_reply_failed",
                    level="error",
                    **context,
                    http_status=http_status,
                    feishu_code=data.get("code"),
                    feishu_msg=data.get("msg"),
                )
                return {"success": False, "error": {"code": data.get("code"), "msg": data.get("msg")}}
            self._log_event(
                "feishu_reply_api_success",
                **context,
                http_status=http_status,
                feishu_code=data.get("code"),
                feishu_msg=data.get("msg"),
            )
            return {"success": True, "response": {"code": data.get("code"), "msg": data.get("msg")}}
        except HTTPError as exc:
            error_data = self._read_feishu_error(exc)
            self._log_event(
                "feishu_reply_failed",
                level="error",
                **context,
                http_status=exc.code,
                feishu_code=error_data.get("code"),
                feishu_msg=error_data.get("msg"),
                error_type=type(exc).__name__,
            )
            return {"success": False, "error": {"http_status": exc.code, **error_data}}
        except (URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            self._log_event(
                "feishu_reply_failed",
                level="error",
                **context,
                error_type=type(exc).__name__,
            )
            return {"success": False, "error": str(exc)}

    def _read_feishu_error(self, exc: HTTPError) -> dict[str, Any]:
        try:
            raw = exc.read().decode("utf-8")
            data = json.loads(raw)
            return {"code": data.get("code"), "msg": data.get("msg")}
        except Exception:
            return {"code": None, "msg": None}

    def _format_agent_reply(self, agent_response: dict[str, Any]) -> str:
        text = str(agent_response.get("final_answer") or "").strip()
        return text or "已处理。"

    def _truncate_text(self, text: str, max_chars: int = 1800) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n内容较长，已截断。可在后端查看完整结果。"

    def _log_event(self, action: str, level: str = "info", **fields: Any) -> None:
        safe_fields = {
            "action": action,
            "event_type": fields.get("event_type"),
            "event_id": fields.get("event_id"),
            "message_id": fields.get("message_id"),
            "message_type": fields.get("message_type"),
        }
        for key, value in fields.items():
            if key in safe_fields or key in {"text", "token", "tenant_access_token", "app_secret"}:
                continue
            safe_fields[key] = value
        message = "feishu_event " + json.dumps(safe_fields, ensure_ascii=False, default=str)
        log_method = getattr(logger, level, logger.info)
        log_method(message)

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())


