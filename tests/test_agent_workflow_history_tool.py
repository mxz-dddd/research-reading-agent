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


def fake_workflow_history_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
    if tool_name == "get_latest_workflow":
        return {
            "success": True,
            "data": {
                "run_id": "run-latest",
                "topic": "large language model agent",
                "success": True,
                "dry_run": True,
                "searched_count": 3,
                "accepted_count": 2,
                "ingested_count": 2,
                "warnings": ["dry_run warning"],
                "error": None,
            },
        }
    if tool_name == "list_workflow_history":
        return {
            "success": True,
            "items": [
                {
                    "run_id": "run-history",
                    "topic": "large language model agent",
                    "success": True,
                    "dry_run": True,
                    "searched_count": 3,
                    "accepted_count": 2,
                    "ingested_count": 2,
                    "warnings": [],
                    "error": None,
                }
            ],
        }
    raise AssertionError(f"unexpected tool: {tool_name}")


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("查看最近一次研究闭环结果", "get_latest_workflow"),
        ("上一次 workflow 结果是什么", "get_latest_workflow"),
        ("列出最近的研究流程历史", "list_workflow_history"),
        ("查看 workflow 历史记录", "list_workflow_history"),
    ],
)
def test_agent_routes_workflow_history_queries(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_tool: str,
) -> None:
    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)
    monkeypatch.setattr(ToolRegistry, "call", fake_workflow_history_call)
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
