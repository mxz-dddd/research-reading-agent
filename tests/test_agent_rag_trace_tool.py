from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.orchestrator import AgentOrchestrator
from app.agent.tool_registry import ToolRegistry
from app.main import app


def fake_trace(trace_id: str = "trace_test_1", paper_id: str | None = "12") -> dict[str, Any]:
    return {
        "id": 1,
        "trace_id": trace_id,
        "query": "propagation error",
        "mode": "answer",
        "paper_id": paper_id,
        "top_k": 5,
        "hit_count": 1,
        "no_evidence": False,
        "answer": "fake answer",
        "evidence": [{"chunk_id": "chunk-1", "paper_id": paper_id, "score_reason": "命中 2 个查询词"}],
        "metadata": {"source": "test"},
        "created_at": "2026-01-01T00:00:00Z",
    }


def fake_tool_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
    if tool_name == "get_latest_rag_traces":
        return {"success": True, "items": [fake_trace()]}
    if tool_name == "get_rag_trace_detail":
        return {"success": True, "data": fake_trace(trace_id=kwargs["trace_id"])}
    if tool_name == "get_rag_traces_by_paper":
        return {"success": True, "items": [fake_trace(paper_id=str(kwargs["paper_id"]))]}
    raise AssertionError(f"unexpected tool: {tool_name}")


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("查看最近的 RAG 检索记录", "get_latest_rag_traces"),
        ("查看最近的 RAG 问答记录", "get_latest_rag_traces"),
        ("查看 trace_test_1 的 RAG 证据详情", "get_rag_trace_detail"),
        ("查看论文 P12 的 RAG 查询记录", "get_rag_traces_by_paper"),
    ],
)
def test_agent_routes_rag_trace_tools(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_tool: str,
) -> None:
    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)
    monkeypatch.setattr(ToolRegistry, "call", fake_tool_call)
    client = TestClient(app)

    response = client.post(
        "/api/agent/query",
        json={"user_id": "test-user", "session_id": "test-session", "message": message},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["chosen_tool"] == expected_tool
    assert data["tool_calls"][0]["tool_name"] == expected_tool
    assert data["final_answer"].strip()
    assert data["data"]["success"] is True
    assert data["error"] is None
    assert data["routing_method"] == "fallback"
