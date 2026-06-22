from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.orchestrator import AgentOrchestrator
from app.agent.tool_registry import ToolRegistry
from app.main import app


def fake_tool_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
    assert tool_name == "run_research_workflow"
    return {
        "success": True,
        "topic": kwargs["topic"],
        "dry_run": kwargs.get("dry_run", False),
        "rag_indexed_papers": [
            {
                "paper_id": "1",
                "success": kwargs.get("index_rag", True),
                "chunk_count": 3,
                "warnings": [],
                "error": None,
            }
        ]
        if kwargs.get("index_rag", True)
        else [],
        "steps": [
            {
                "step": "search_papers",
                "success": True,
                "summary": "fake search",
                "data": {},
                "error": None,
            },
            {
                "step": "accept_top_k",
                "success": True,
                "summary": "fake accept",
                "data": {},
                "error": None,
            },
            {
                "step": "index_rag",
                "success": True,
                "summary": "fake rag",
                "data": {},
                "error": None,
            },
        ],
        "searched_papers": [{"id": 1, "title": "Fake Paper"}],
        "accepted_papers": [{"id": 1, "title": "Fake Paper"}],
        "ingested_papers": [{"id": 1, "title": "Fake Paper"}],
        "knowledge": {"id": 1},
        "innovation": {"id": 1},
        "warnings": [],
        "error": None,
    }


@pytest.mark.parametrize(
    "message",
    [
        "围绕 large language model agent 完整跑一遍研究流程",
        "帮我从论文搜索到创新点生成完整执行一遍",
        "请对 VLF timing correction 做一个完整研究闭环",
        "一键完成这个方向的论文搜索、接收、知识树和创新点",
    ],
)
def test_agent_routes_workflow_requests_to_workflow_tool(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
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
    assert data["chosen_tool"] == "run_research_workflow"
    assert data["tool_calls"]
    assert data["tool_calls"][0]["tool_name"] == "run_research_workflow"
    assert data["final_answer"].strip()
    assert data["data"]["success"] is True
    assert data["error"] is None
    assert data["routing_method"] == "fallback"


@pytest.mark.parametrize(
    "message",
    [
        "围绕 large language model agent 完整跑一遍研究流程并建立 RAG 索引",
        "请对 VLF timing correction 做完整研究闭环并建立检索索引",
    ],
)
def test_agent_routes_workflow_requests_with_rag_indexing(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
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
    assert data["chosen_tool"] == "run_research_workflow"
    assert data["tool_calls"][0]["arguments"]["index_rag"] is True
    assert data["data"]["rag_indexed_papers"]
    assert "RAG 索引" in data["final_answer"]


@pytest.mark.parametrize(
    "message",
    [
        "以 dry run 方式围绕 large language model agent 完整跑一遍研究流程",
        "不联网演示一下研究闭环",
        "用模拟数据跑完整研究流程",
        "mock 完整研究流程",
    ],
)
def test_agent_routes_dry_run_workflow_requests_with_dry_run_true(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
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
    assert data["chosen_tool"] == "run_research_workflow"
    assert data["tool_calls"][0]["tool_name"] == "run_research_workflow"
    assert data["tool_calls"][0]["arguments"]["dry_run"] is True
    assert data["data"]["dry_run"] is True
    assert "dry_run" in data["final_answer"]
    assert data["error"] is None
    assert data["routing_method"] == "fallback"
