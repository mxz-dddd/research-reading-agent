from datetime import date

from app.schemas.conversation import ConversationState
from app.services.conversation_followup_service import ConversationFollowupService


def _state() -> ConversationState:
    return ConversationState(
        session_id="s1",
        channel="feishu",
        chat_id="chat1",
        user_id="user1",
        thread_id=None,
        last_intent="search_papers",
        last_tool="search_papers",
        last_arguments={
            "query": "VLF传播时延",
            "limit": 5,
            "published_from": None,
            "published_to": None,
        },
        last_result_refs=[
            {"position": 1, "paper_id": 101, "title": "Paper 1", "url": "https://arxiv.org/abs/1"},
            {"position": 2, "paper_id": 202, "title": "Paper 2", "url": "https://arxiv.org/abs/2"},
            {"position": 3, "paper_id": 303, "title": "Paper 3", "url": "https://arxiv.org/abs/3"},
        ],
        last_user_message="搜索5篇VLF传播时延论文",
        last_assistant_summary="找到 5 篇相关论文",
        last_focused_paper_id=101,
        updated_at="2026-06-18T00:00:00+00:00",
        expires_at="2026-06-25T00:00:00+00:00",
    )


def test_time_followup_inherits_query_and_limit() -> None:
    resolution = ConversationFollowupService().resolve("要近十年的", _state())

    assert resolution.is_followup is True
    assert resolution.tool_name == "search_papers"
    assert resolution.arguments["topic"] == "VLF传播时延"
    assert resolution.arguments["max_results"] == 5
    assert (
        resolution.arguments["published_from"]
        == date(date.today().year - 10, date.today().month, date.today().day).isoformat()
    )
    assert resolution.arguments["published_to"] == date.today().isoformat()


def test_quantity_followup_keeps_query_and_time() -> None:
    state = _state()
    state = ConversationState(
        **{
            **state.__dict__,
            "last_arguments": {
                "query": "VLF传播时延",
                "limit": 5,
                "published_from": "2016-06-18",
                "published_to": "2026-06-18",
            },
        }
    )

    resolution = ConversationFollowupService().resolve("只要3篇", state)

    assert resolution.tool_name == "search_papers"
    assert resolution.arguments["topic"] == "VLF传播时延"
    assert resolution.arguments["max_results"] == 3
    assert resolution.arguments["published_from"] == "2016-06-18"


def test_change_to_recent_five_years() -> None:
    resolution = ConversationFollowupService().resolve("换成近五年的", _state())

    assert resolution.tool_name == "search_papers"
    assert resolution.arguments["topic"] == "VLF传播时延"
    assert (
        resolution.arguments["published_from"]
        == date(date.today().year - 5, date.today().month, date.today().day).isoformat()
    )


def test_ordinal_reference_resolves_detail_to_real_paper_id() -> None:
    resolution = ConversationFollowupService().resolve("第2篇", _state())

    assert resolution.tool_name == "get_paper_detail"
    assert resolution.arguments == {"paper_id": 202}


def test_accept_ordinal_uses_real_paper_id_not_ordinal() -> None:
    resolution = ConversationFollowupService().resolve("接收第2篇", _state())

    assert resolution.tool_name == "accept_paper"
    assert resolution.arguments == {"paper_id": 202}


def test_ingest_ordinal_uses_real_paper_id() -> None:
    resolution = ConversationFollowupService().resolve("对第2篇做深入阅读", _state())

    assert resolution.tool_name == "ingest_paper"
    assert resolution.arguments == {"paper_id": 202}


def test_pronoun_reference_uses_focused_paper() -> None:
    resolution = ConversationFollowupService().resolve("接收它", _state())

    assert resolution.tool_name == "accept_paper"
    assert resolution.arguments == {"paper_id": 101}


def test_continue_search_inherits_context() -> None:
    resolution = ConversationFollowupService().resolve("再来5篇", _state())

    assert resolution.tool_name == "search_papers"
    assert resolution.arguments["topic"] == "VLF传播时延"
    assert resolution.arguments["max_results"] == 5
    assert resolution.append_mode is True
    assert resolution.exclude_previous_results is True
    assert resolution.requested_additional_limit == 5
    assert resolution.arguments["result_offset"] == 3
    assert resolution.arguments["exclude_paper_ids"] == [101, 202, 303]
    assert resolution.arguments["exclude_arxiv_ids"] == ["1", "2", "3"]


def test_desired_total_only_requests_missing_results() -> None:
    state = _state()
    refs = [
        {
            "position": index,
            "paper_id": 100 + index,
            "title": f"Paper {index}",
            "url": f"https://arxiv.org/abs/{index}",
        }
        for index in range(1, 6)
    ]
    state = ConversationState(**{**state.__dict__, "last_result_refs": refs})

    resolution = ConversationFollowupService().resolve("我一共要10篇，再补充5篇", state)

    assert resolution.append_mode is True
    assert resolution.desired_total_limit == 10
    assert resolution.requested_additional_limit == 5
    assert resolution.arguments["max_results"] == 5


def test_desired_total_equal_to_current_results_does_not_search() -> None:
    resolution = ConversationFollowupService().resolve("一共要5篇", _state_with_results(5))

    assert resolution.direct_reply is True
    assert resolution.tool_name is None
    assert "已满足" in resolution.resolved_message
    assert "5 篇" in resolution.resolved_message


def test_desired_total_below_current_results_does_not_search_or_clear_context() -> None:
    resolution = ConversationFollowupService().resolve("一共要3篇", _state_with_results(5))

    assert resolution.direct_reply is True
    assert resolution.tool_name is None
    assert resolution.clear_context is False
    assert "超过" in resolution.resolved_message


def test_desired_total_from_empty_results_searches_requested_count() -> None:
    resolution = ConversationFollowupService().resolve("一共要5篇", _state_with_results(0))

    assert resolution.tool_name == "search_papers"
    assert resolution.arguments["max_results"] == 5
    assert resolution.append_mode is True


def test_desired_total_without_topic_context_requests_topic() -> None:
    state = _state_with_results(0)
    state = ConversationState(**{**state.__dict__, "last_arguments": {"query": None, "limit": 5}})

    resolution = ConversationFollowupService().resolve("一共要5篇", state)

    assert resolution.direct_reply is True
    assert resolution.tool_name is None
    assert "研究主题" in resolution.resolved_message


def test_time_change_replaces_instead_of_appending() -> None:
    resolution = ConversationFollowupService().resolve("换成近五年的", _state())

    assert resolution.append_mode is False
    assert resolution.arguments["exclude_urls"] == []
    assert resolution.arguments["result_offset"] == 0


def test_new_task_does_not_inherit_search_context() -> None:
    resolution = ConversationFollowupService().resolve("帮我生成知识树", _state())

    assert resolution.is_followup is False


def test_clear_context_command() -> None:
    resolution = ConversationFollowupService().resolve("重新开始", _state())

    assert resolution.clear_context is True
    assert resolution.resolved_message == "已清除当前对话上下文，可以开始新的任务。"


def test_no_context_means_not_followup() -> None:
    resolution = ConversationFollowupService().resolve("要近十年的", None)

    assert resolution.is_followup is False


def _state_with_results(count: int) -> ConversationState:
    state = _state()
    refs = [
        {
            "position": index,
            "paper_id": 100 + index,
            "title": f"Paper {index}",
            "url": f"https://arxiv.org/abs/{index}",
        }
        for index in range(1, count + 1)
    ]
    return ConversationState(**{**state.__dict__, "last_result_refs": refs})


def test_batch_ingest_this_five_uses_current_results() -> None:
    resolution = ConversationFollowupService().resolve(
        "对这五篇都进行深入阅读", _state_with_results(5)
    )

    assert resolution.tool_name == "batch_ingest_papers"
    assert resolution.arguments == {
        "paper_ids": [101, 102, 103, 104, 105],
        "source_positions": [1, 2, 3, 4, 5],
    }
    assert "read_papers" not in resolution.resolved_message


def test_batch_ingest_all_uses_all_current_results() -> None:
    resolution = ConversationFollowupService().resolve(
        "对刚才全部论文深入阅读", _state_with_results(5)
    )

    assert resolution.arguments["paper_ids"] == [101, 102, 103, 104, 105]


def test_batch_ingest_front_five_and_explicit_range() -> None:
    state = _state_with_results(10)

    front = ConversationFollowupService().resolve("对前5篇做深入阅读", state)
    explicit = ConversationFollowupService().resolve("对第1到第5篇做深入阅读", state)
    appended = ConversationFollowupService().resolve("对第6到第10篇做深入阅读", state)

    assert front.arguments["source_positions"] == [1, 2, 3, 4, 5]
    assert explicit.arguments["paper_ids"] == [101, 102, 103, 104, 105]
    assert appended.arguments["paper_ids"] == [106, 107, 108, 109, 110]


def test_batch_ingest_without_context_returns_direct_help() -> None:
    resolution = ConversationFollowupService().resolve("全部深入阅读", None)

    assert resolution.direct_reply is True
    assert resolution.tool_name is None
    assert "先搜索" not in resolution.resolved_message or "论文" in resolution.resolved_message
    assert "read_papers" not in resolution.resolved_message


def test_llm_read_papers_is_mapped_to_batch_ingest() -> None:
    class FakeLLM:
        def is_configured(self):
            return True

        def responses_text(self, *args, **kwargs):
            return '{"is_followup": true, "intent": "read_papers", "tool_name": "read_papers", "arguments": {}, "confidence": 0.8}'

    resolution = ConversationFollowupService(llm_client=FakeLLM()).resolve(
        "把它们处理一下",
        _state_with_results(5),
    )

    assert resolution.tool_name == "batch_ingest_papers"
    assert resolution.arguments["paper_ids"] == [101, 102, 103, 104, 105]


def test_pronoun_deep_read_still_uses_single_ingest() -> None:
    resolution = ConversationFollowupService().resolve("对它做深入阅读", _state())

    assert resolution.tool_name == "ingest_paper"
    assert resolution.arguments == {"paper_id": 101}


def test_batch_all_over_ten_returns_limit_prompt() -> None:
    resolution = ConversationFollowupService().resolve("全部深入阅读", _state_with_results(11))

    assert resolution.direct_reply is True
    assert resolution.tool_name is None
    assert "当前列表有 11 篇" in resolution.resolved_message
    assert "一次最多深入阅读 10 篇" in resolution.resolved_message
