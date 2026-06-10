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

REQUIRED_RESPONSE_FIELDS = {
    "success",
    "intent",
    "chosen_tool",
    "tool_calls",
    "final_answer",
    "data",
    "error",
    "routing_method",
}


def fake_tool_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
    if tool_name == "search_papers":
        return [
            {
                "id": 101,
                "title": "Fake LLM Agent Paper",
                "status": "found",
            },
            {
                "id": 102,
                "title": "Fake Agent Evaluation Paper",
                "status": "found",
            },
        ]
    if tool_name == "accept_paper":
        return {
            "id": kwargs["paper_id"],
            "title": "Fake Accepted Paper",
            "status": "accepted",
            "is_accepted": 1,
        }
    if tool_name == "ingest_paper":
        return {
            "id": kwargs["paper_id"],
            "title": "Fake Ingested Paper",
            "status": "ingested",
            "ingest_status": "abstract_only",
            "local_summary_path": "data/archives/summaries/fake.md",
        }
    if tool_name == "list_accepted_papers":
        return [
            {
                "id": 12,
                "title": "Fake Accepted Paper",
                "status": "accepted",
            }
        ]
    if tool_name == "get_paper_detail":
        return {
            "id": kwargs["paper_id"],
            "title": "Fake Paper Detail",
            "status": "accepted",
            "ingest_status": "accepted",
            "worth_reading": "值得继续看",
            "local_summary_path": None,
        }
    if tool_name == "generate_knowledge":
        return {
            "id": 1,
            "source_paper_count": 2,
            "generation_method": "fallback",
            "local_markdown_path": "data/archives/knowledge/fake.md",
        }
    if tool_name == "generate_innovation":
        return {
            "id": 1,
            "source_paper_count": 2,
            "generation_method": "fallback",
            "local_markdown_path": "data/archives/innovation/fake.md",
        }
    if tool_name == "help":
        return {
            "capabilities": [
                "搜索论文",
                "接收论文",
                "深入阅读并归档",
            ]
        }
    raise AssertionError(f"Unexpected tool call: {tool_name}")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)
    monkeypatch.setattr(ToolRegistry, "call", fake_tool_call)
    return TestClient(app)


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("你能做什么", "help"),
        ("帮我搜索 3 篇关于 large language model agent 的论文", "search_papers"),
        ("接收论文 P12", "accept_paper"),
        ("深入阅读论文 P12", "ingest_paper"),
        ("列出已接收论文", "list_accepted_papers"),
        ("查看论文 P12 的详情", "get_paper_detail"),
        ("根据已接收论文生成知识树", "generate_knowledge"),
        ("基于这些论文生成创新点", "generate_innovation"),
    ],
)
def test_agent_query_endpoint_response_shape(
    client: TestClient,
    message: str,
    expected_tool: str,
) -> None:
    response = client.post(
        "/api/agent/query",
        json={
            "user_id": "test-user",
            "session_id": "test-session",
            "message": message,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert REQUIRED_RESPONSE_FIELDS.issubset(data.keys())
    assert data["success"] is True
    assert data["chosen_tool"] == expected_tool
    assert data["tool_calls"]
    assert data["tool_calls"][0]["tool_name"] == expected_tool
    assert data["final_answer"].strip()
    assert data["data"] is not None
    assert data["error"] is None
    assert data["routing_method"] == "fallback"
