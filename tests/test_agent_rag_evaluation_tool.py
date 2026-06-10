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


def fake_tool_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
    if tool_name == "add_rag_trace_feedback":
        return {
            "success": True,
            "data": {
                "id": 1,
                "feedback_id": "feedback_test_1",
                "trace_id": kwargs["trace_id"],
                "relevance_label": kwargs["relevance_label"],
                "expected_terms": kwargs.get("expected_terms") or [],
                "notes": kwargs.get("notes"),
                "created_at": "2026-01-01T00:00:00Z",
            },
            "message": None,
            "error": None,
        }
    if tool_name == "get_rag_evaluation_summary":
        return {
            "success": True,
            "summary": {
                "total_traces": 3,
                "answered_traces": 2,
                "no_evidence_traces": 1,
                "total_feedback": 2,
                "relevance_rate": 0.5,
                "no_evidence_accuracy": 1.0,
                "label_distribution": {"relevant": 1, "no_evidence_correct": 1},
            },
        }
    if tool_name == "get_rag_trace_evaluation_detail":
        return {
            "success": True,
            "trace": {
                "id": 1,
                "trace_id": kwargs["trace_id"],
                "query": "retrieval agent",
                "mode": "answer",
                "paper_id": "12",
                "top_k": 5,
                "hit_count": 1,
                "no_evidence": False,
                "answer": "fake answer",
                "evidence": [],
                "metadata": {},
                "created_at": "2026-01-01T00:00:00Z",
            },
            "latest_feedback": {
                "id": 1,
                "feedback_id": "feedback_test_1",
                "trace_id": kwargs["trace_id"],
                "relevance_label": "relevant",
                "expected_terms": [],
                "notes": None,
                "created_at": "2026-01-01T00:00:00Z",
            },
            "message": None,
            "error": None,
        }
    raise AssertionError(f"unexpected tool: {tool_name}")


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("把 trace_test_1 标注为 relevant", "add_rag_trace_feedback"),
        ("给 trace_test_1 添加反馈：部分相关", "add_rag_trace_feedback"),
        ("查看 RAG 评估摘要", "get_rag_evaluation_summary"),
        ("查看 RAG 检索质量统计", "get_rag_evaluation_summary"),
        ("查看 trace_test_1 的评估详情", "get_rag_trace_evaluation_detail"),
    ],
)
def test_agent_routes_rag_evaluation_tools(
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
