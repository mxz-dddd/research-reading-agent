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


def fake_workflow_report_call(self: ToolRegistry, tool_name: str, **kwargs: Any) -> Any:
    if tool_name in {"generate_workflow_report", "get_workflow_report"}:
        run_id = kwargs.get("run_id") or "run-latest"
        return {
            "success": True,
            "run_id": run_id,
            "report_path": f"data/archives/workflow_reports/workflow_report_{run_id}.md",
            "report_markdown": "# Research Workflow Report\n\nfake report",
            "error": None,
        }
    raise AssertionError(f"unexpected tool: {tool_name}")


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("把最近一次研究闭环生成报告", "generate_workflow_report"),
        ("根据上一次 workflow 生成研究报告", "generate_workflow_report"),
        ("查看最近一次 workflow 的报告", "get_workflow_report"),
        ("给 run_report_001 生成研究报告", "generate_workflow_report"),
        ("查看 run_report_001 的研究报告", "get_workflow_report"),
    ],
)
def test_agent_routes_workflow_report_queries(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_tool: str,
) -> None:
    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)
    monkeypatch.setattr(ToolRegistry, "call", fake_workflow_report_call)
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
    assert data["data"]["report_path"]
    assert data["error"] is None
    assert data["routing_method"] == "fallback"
