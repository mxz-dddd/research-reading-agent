from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.core.database as database
from app.core.database import init_db
from app.repositories.conversation_repo import ConversationRepository
from app.schemas.agent import AgentQueryResponse, AgentToolCall
from app.services.conversation_context_service import ConversationContextService


@pytest.fixture
def conversation_service(tmp_path, monkeypatch):
    monkeypatch.setattr(
        database, "settings", SimpleNamespace(database_path=str(tmp_path / "test.db"))
    )
    init_db()
    return ConversationContextService(ConversationRepository())


def test_save_and_reload_search_state_persists_after_service_recreate(
    conversation_service, tmp_path, monkeypatch
) -> None:
    response = AgentQueryResponse(
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
    )

    conversation_service.save_user_turn(
        session_id="s1", message="搜索5篇VLF传播时延论文", message_id="m1"
    )
    conversation_service.update_from_agent_response(
        session_id="s1",
        channel="feishu",
        chat_id="chat1",
        user_id="user1",
        thread_id=None,
        user_message="搜索5篇VLF传播时延论文",
        assistant_text=response.final_answer,
        response=response,
    )

    reloaded = ConversationContextService(ConversationRepository()).get_state("s1")

    assert reloaded is not None
    assert reloaded.last_tool == "search_papers"
    assert reloaded.last_arguments["query"] == "VLF传播时延"
    assert reloaded.last_arguments["limit"] == 5
    assert reloaded.last_result_refs[1]["paper_id"] == 102


def test_duplicate_message_id_does_not_save_turn_twice(conversation_service) -> None:
    conversation_service.save_user_turn(session_id="s1", message="hello", message_id="m1")
    conversation_service.save_user_turn(session_id="s1", message="hello again", message_id="m1")

    turns = conversation_service.recent_turns("s1", limit=10)

    assert len([turn for turn in turns if turn.role == "user"]) == 1


def test_clear_session_removes_turns_and_state(conversation_service) -> None:
    response = AgentQueryResponse(
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
        final_answer="ok",
        data=[],
    )
    conversation_service.save_user_turn(session_id="s1", message="搜索 VLF", message_id="m1")
    conversation_service.update_from_agent_response(
        session_id="s1",
        channel="feishu",
        chat_id="chat1",
        user_id="user1",
        thread_id=None,
        user_message="搜索 VLF",
        assistant_text="ok",
        response=response,
    )

    conversation_service.clear_session("s1")

    assert conversation_service.get_state("s1") is None
    assert conversation_service.recent_turns("s1") == []


def test_expired_state_is_ignored(conversation_service) -> None:
    expired = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    conversation_service.repo.upsert_state(
        session_id="s1",
        channel="feishu",
        chat_id="chat1",
        user_id="user1",
        thread_id=None,
        last_intent="search_papers",
        last_tool="search_papers",
        last_arguments={"query": "VLF", "limit": 5},
        last_result_refs=[],
        last_user_message="search",
        last_assistant_summary="ok",
        last_focused_paper_id=None,
        expires_at=expired,
    )

    assert conversation_service.get_state("s1") is None


def test_session_lock_serializes_updates(conversation_service) -> None:
    with conversation_service.session_lock("s1"):
        with conversation_service.session_lock("s1"):
            conversation_service.save_user_turn(session_id="s1", message="nested", message_id="m1")

    assert len(conversation_service.recent_turns("s1")) == 1


def test_append_search_accumulates_refs_and_replace_search_resets_them(
    conversation_service,
) -> None:
    first = AgentQueryResponse(
        success=True,
        intent="search_papers",
        chosen_tool="search_papers",
        tool_calls=[
            AgentToolCall(
                tool_name="search_papers",
                arguments={"topic": "VLF", "max_results": 2},
                success=True,
            )
        ],
        final_answer="first",
        data=[
            {"id": 101, "title": "P1", "url": "https://arxiv.org/abs/1"},
            {"id": 102, "title": "P2", "url": "https://arxiv.org/abs/2"},
        ],
    )
    first_state = conversation_service.update_from_agent_response(
        session_id="append",
        channel="feishu",
        chat_id="c",
        user_id="u",
        thread_id=None,
        user_message="搜索",
        assistant_text="first",
        response=first,
    )
    appended = AgentQueryResponse(
        success=True,
        intent="search_papers",
        chosen_tool="search_papers",
        tool_calls=[
            AgentToolCall(
                tool_name="search_papers",
                arguments={"topic": "VLF", "max_results": 2, "append_mode": True},
                success=True,
            )
        ],
        final_answer="more",
        data=[
            {"id": 103, "title": "P3", "url": "https://arxiv.org/abs/3"},
            {"id": 104, "title": "P4", "url": "https://arxiv.org/abs/4"},
        ],
    )
    appended_state = conversation_service.update_from_agent_response(
        session_id="append",
        channel="feishu",
        chat_id="c",
        user_id="u",
        thread_id=None,
        user_message="再来2篇",
        assistant_text="more",
        response=appended,
        previous_state=first_state,
    )

    assert [item["position"] for item in appended_state.last_result_refs] == [1, 2, 3, 4]
    assert [item["paper_id"] for item in appended_state.last_result_refs] == [101, 102, 103, 104]

    replacement = AgentQueryResponse(
        success=True,
        intent="search_papers",
        chosen_tool="search_papers",
        tool_calls=[
            AgentToolCall(
                tool_name="search_papers",
                arguments={"topic": "solar flare", "max_results": 1},
                success=True,
            )
        ],
        final_answer="replacement",
        data=[{"id": 201, "title": "New", "url": "https://arxiv.org/abs/new"}],
    )
    replaced_state = conversation_service.update_from_agent_response(
        session_id="append",
        channel="feishu",
        chat_id="c",
        user_id="u",
        thread_id=None,
        user_message="换个主题",
        assistant_text="replacement",
        response=replacement,
        previous_state=appended_state,
    )

    assert replaced_state.last_result_refs == [
        {"position": 1, "paper_id": 201, "title": "New", "url": "https://arxiv.org/abs/new"}
    ]


def test_batch_ingest_preserves_result_refs_and_tracks_last_success(conversation_service) -> None:
    refs = [
        {
            "position": index,
            "paper_id": 100 + index,
            "title": f"P{index}",
            "url": f"https://arxiv.org/abs/{index}",
        }
        for index in range(1, 6)
    ]
    previous = conversation_service.repo.upsert_state(
        session_id="batch",
        channel="feishu",
        chat_id="c",
        user_id="u",
        thread_id=None,
        last_intent="search_papers",
        last_tool="search_papers",
        last_arguments={"query": "VLF", "limit": 5},
        last_result_refs=refs,
        last_user_message="search",
        last_assistant_summary="found",
        last_focused_paper_id=101,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    response = AgentQueryResponse(
        success=True,
        intent="batch_ingest_papers",
        chosen_tool="batch_ingest_papers",
        tool_calls=[
            AgentToolCall(
                tool_name="batch_ingest_papers",
                arguments={"paper_ids": [101, 102, 103], "source_positions": [1, 2, 3]},
                success=True,
            )
        ],
        final_answer="done",
        data={
            "items": [
                {"paper_id": 101, "status": "success"},
                {"paper_id": 102, "status": "failed"},
                {"paper_id": 103, "status": "success"},
            ]
        },
    )

    state = conversation_service.update_from_agent_response(
        session_id="batch",
        channel="feishu",
        chat_id="c",
        user_id="u",
        thread_id=None,
        user_message="全部深入阅读",
        assistant_text="done",
        response=response,
        previous_state=previous,
    )

    assert state.last_tool == "batch_ingest_papers"
    assert state.last_arguments["paper_ids"] == [101, 102, 103]
    assert state.last_arguments["source_positions"] == [1, 2, 3]
    assert state.last_result_refs == refs
    assert state.last_focused_paper_id == 103
