from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.argument_resolver import resolve_arguments
from app.agent.fallback_router import route_with_fallback
from app.agent.orchestrator import AgentOrchestrator
from app.schemas.agent import AgentQueryRequest


class FakeSessionRepo:
    def __init__(self, resolved_positions: dict[int, int] | None = None) -> None:
        self.resolved_positions = resolved_positions or {}
        self.calls: list[tuple[str, str, int]] = []

    def resolve_recent_position(self, user_id: str, session_id: str, position: int) -> int | None:
        self.calls.append((user_id, session_id, position))
        return self.resolved_positions.get(position)


class ExplodingRegistry:
    def call(self, tool_name: str, **kwargs: Any) -> Any:
        raise AssertionError("ToolRegistry.call should not run in this missing-argument test")


@pytest.fixture
def orchestrator() -> AgentOrchestrator:
    agent = AgentOrchestrator.__new__(AgentOrchestrator)
    agent.session_repo = FakeSessionRepo()
    return agent


def resolve_message(
    orchestrator: AgentOrchestrator,
    message: str,
    *,
    user_id: str = "test-user",
    session_id: str = "test-session",
) -> dict[str, Any]:
    route = route_with_fallback(message)
    payload = AgentQueryRequest(user_id=user_id, session_id=session_id, message=message)
    return orchestrator._resolve_arguments(
        arguments=dict(route.get("arguments", {})),
        payload=payload,
        tool_name=route["tool_name"],
    )


def resolve_message_direct(
    session_repo: FakeSessionRepo,
    message: str,
    *,
    user_id: str = "test-user",
    session_id: str = "test-session",
) -> dict[str, Any]:
    route = route_with_fallback(message)
    payload = AgentQueryRequest(user_id=user_id, session_id=session_id, message=message)
    return resolve_arguments(
        arguments=dict(route.get("arguments", {})),
        payload=payload,
        tool_name=route["tool_name"],
        session_repo=session_repo,
    )


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("接收论文 P12", "accept_paper"),
        ("深入阅读论文 P12", "ingest_paper"),
        ("查看论文 P12 的详情", "get_paper_detail"),
    ],
)
def test_resolves_direct_paper_id(
    orchestrator: AgentOrchestrator,
    message: str,
    expected_tool: str,
) -> None:
    route = route_with_fallback(message)

    assert route["tool_name"] == expected_tool
    assert route["arguments"] == {"paper_id": 12}
    assert resolve_message(orchestrator, message) == {"paper_id": 12}


def test_resolves_accept_recent_result_ordinal() -> None:
    agent = AgentOrchestrator.__new__(AgentOrchestrator)
    agent.session_repo = FakeSessionRepo({2: 102})

    resolved = resolve_message(agent, "接收第 2 篇")

    assert resolved == {"paper_id": 102}
    assert agent.session_repo.calls == [("test-user", "test-session", 2)]


def test_direct_resolver_resolves_recent_result_ordinal() -> None:
    session_repo = FakeSessionRepo({2: 202})

    resolved = resolve_message_direct(session_repo, "接收第 2 篇")

    assert resolved == {"paper_id": 202}
    assert session_repo.calls == [("test-user", "test-session", 2)]


def test_resolves_ingest_recent_result_ordinal() -> None:
    agent = AgentOrchestrator.__new__(AgentOrchestrator)
    agent.session_repo = FakeSessionRepo({3: 103})

    resolved = resolve_message(agent, "深入阅读第 3 篇")

    assert resolved == {"paper_id": 103}
    assert agent.session_repo.calls == [("test-user", "test-session", 3)]


def test_missing_required_paper_argument_returns_safe_agent_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = AgentOrchestrator.__new__(AgentOrchestrator)
    agent.session_repo = FakeSessionRepo()
    agent.registry = ExplodingRegistry()
    monkeypatch.setattr(agent, "_route_with_llm", lambda message: None)

    response = agent.query(AgentQueryRequest(message="接收论文"))

    assert response.success is False
    assert response.chosen_tool == "accept_paper"
    assert response.error == "请提供 paper_id，或使用“第 N 篇”引用最近一次搜索结果。"
    assert response.final_answer.startswith("我没能完成这个操作：")
    assert response.tool_calls
    assert response.tool_calls[0].success is False
