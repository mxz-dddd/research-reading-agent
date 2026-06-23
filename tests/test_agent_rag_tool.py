from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.orchestrator import AgentOrchestrator
from app.agent.tool_registry import ToolRegistry
from app.main import app


def fake_rag_tool_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
    if tool_name == "index_paper_rag":
        return {
            "success": True,
            "paper_id": str(kwargs["paper_id"]),
            "chunk_count": 3,
            "warnings": [],
            "error": None,
        }
    if tool_name == "rag_search":
        return {
            "success": True,
            "query": kwargs["query"],
            "evidence_chunks": [
                {
                    "score": 2,
                    "chunk_id": "chunk-1",
                    "paper_id": "12",
                    "chunk_index": 0,
                    "matched_terms": ["error", "propagation"],
                    "content": "Propagation error correction",
                    "content_preview": "Propagation error correction",
                    "source_path": "fake.txt",
                    "metadata": {},
                    "score_reason": "命中 2 个查询词：error, propagation",
                }
            ],
            "message": None,
            "no_evidence": False,
            "error": None,
        }
    if tool_name == "rag_answer":
        return {
            "success": True,
            "query": kwargs["query"],
            "answer": "以下回答基于已索引论文片段：\n[Evidence 1] fake evidence",
            "evidence_chunks": [
                {
                    "score": 2,
                    "chunk_id": "chunk-1",
                    "paper_id": "12",
                    "chunk_index": 0,
                    "matched_terms": ["contribution"],
                    "content": "Main contribution",
                    "content_preview": "Main contribution",
                    "source_path": "fake.txt",
                    "metadata": {},
                    "score_reason": "命中 1 个查询词：contribution",
                }
            ],
            "warning": "RAG v1 warning",
            "no_evidence": False,
            "error": None,
        }
    raise AssertionError(f"unexpected tool: {tool_name}")


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("把论文 P12 建立 RAG 索引", "index_paper_rag"),
        ("在已索引论文中搜索 propagation error", "rag_search"),
        ("基于论文内容回答 main contribution 是什么", "rag_answer"),
        ("用 RAG 回答这篇论文的方法是什么", "rag_answer"),
    ],
)
def test_agent_routes_rag_tools(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_tool: str,
) -> None:
    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)
    monkeypatch.setattr(ToolRegistry, "call", fake_rag_tool_call)
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
    if expected_tool == "rag_search":
        assert "命中词" in data["final_answer"]
    if expected_tool == "rag_answer":
        assert "[Evidence 1]" in data["final_answer"]


def test_agent_rag_answer_no_evidence_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_no_evidence_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
        assert tool_name == "rag_answer"
        return {
            "success": True,
            "query": kwargs["query"],
            "answer": "当前已索引论文中没有检索到足够证据，无法基于文档回答该问题。",
            "evidence_chunks": [],
            "warning": "RAG v1 warning",
            "no_evidence": True,
            "error": None,
        }

    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)
    monkeypatch.setattr(ToolRegistry, "call", fake_no_evidence_call)
    client = TestClient(app)

    response = client.post(
        "/api/agent/query",
        json={
            "user_id": "test-user",
            "session_id": "test-session",
            "message": "基于论文内容回答 nonexistent query",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["chosen_tool"] == "rag_answer"
    assert "没有检索到足够证据" in data["final_answer"]
