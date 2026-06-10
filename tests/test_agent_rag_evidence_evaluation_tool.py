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
    if tool_name == "add_rag_evidence_feedback":
        return {
            "success": True,
            "data": {
                "id": 1,
                "evidence_feedback_id": "evidence_feedback_test_1",
                "trace_id": kwargs["trace_id"],
                "chunk_id": kwargs.get("chunk_id") or "chunk_test_1",
                "rank": kwargs.get("rank") or 1,
                "relevance_score": kwargs["relevance_score"],
                "relevance_label": "relevant",
                "notes": kwargs.get("notes"),
                "created_at": "2026-01-01T00:00:00Z",
            },
            "message": None,
            "error": None,
        }
    if tool_name == "get_rag_evidence_evaluation_summary":
        return {
            "success": True,
            "summary": {
                "total_traces_with_evidence_feedback": 2,
                "total_evidence_feedback": 3,
                "recall_at_1": 0.5,
                "recall_at_3": 1.0,
                "recall_at_5": 1.0,
                "mrr": 0.75,
                "ndcg_at_5": 0.8,
            },
            "message": None,
        }
    if tool_name == "get_rag_trace_evidence_evaluation":
        return {
            "success": True,
            "trace_id": kwargs["trace_id"],
            "evidence": [
                {
                    "rank": 1,
                    "chunk_id": "chunk_test_1",
                    "score": 2,
                    "latest_feedback": {"relevance_label": "relevant"},
                }
            ],
            "message": None,
            "error": None,
        }
    raise AssertionError(f"unexpected tool: {tool_name}")


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("把 trace_test_1 的第 1 条证据标注为相关", "add_rag_evidence_feedback"),
        ("把 trace_test_1 的 chunk_test_1 标注为相关", "add_rag_evidence_feedback"),
        ("查看 RAG evidence-level 评估摘要", "get_rag_evidence_evaluation_summary"),
        ("统计 RAG 的 Recall@K 和 MRR", "get_rag_evidence_evaluation_summary"),
        ("查看 trace_test_1 的证据级评估详情", "get_rag_trace_evidence_evaluation"),
    ],
)
def test_agent_routes_rag_evidence_evaluation_tools(
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
