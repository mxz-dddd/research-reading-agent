import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.orchestrator import AgentOrchestrator
from app.api import routes_agent, routes_workflow
from app.core import database
from app.main import app


def test_research_workflow_dry_run_closed_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    test_db = tmp_path / "closed_loop.db"
    report_dir = tmp_path / "workflow_reports"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()

    monkeypatch.setattr(routes_workflow.workflow_report_service, "report_dir", report_dir)
    monkeypatch.setattr(
        routes_agent.agent_service.orchestrator.registry.workflow_report_service,
        "report_dir",
        report_dir,
    )
    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)

    client = TestClient(app)

    run_response = client.post(
        "/api/workflow/run",
        json={
            "topic": "large language model agent",
            "dry_run": True,
            "max_results": 3,
            "accept_top_k": 2,
        },
    )

    assert run_response.status_code == 200
    run_data = run_response.json()
    assert run_data["success"] is True
    assert run_data["dry_run"] is True
    assert run_data["run_id"]
    assert run_data["steps"]
    assert any(step["step"] == "index_rag" for step in run_data["steps"])
    assert run_data["rag_indexed_papers"]
    assert any("dry_run 模式" in warning for warning in run_data["warnings"])
    run_id = run_data["run_id"]

    latest_response = client.get("/api/workflow/latest")

    assert latest_response.status_code == 200
    latest_data = latest_response.json()
    assert latest_data["success"] is True
    assert latest_data["data"]["run_id"] == run_id
    assert latest_data["data"]["dry_run"] is True

    history_response = client.get("/api/workflow/history?limit=5")

    assert history_response.status_code == 200
    history_data = history_response.json()
    assert history_data["success"] is True
    assert history_data["items"]
    assert any(item["run_id"] == run_id for item in history_data["items"])

    detail_response = client.get(f"/api/workflow/{run_id}")

    assert detail_response.status_code == 200
    detail_data = detail_response.json()
    assert detail_data["success"] is True
    assert detail_data["data"]["run_id"] == run_id
    assert detail_data["data"]["topic"] == "large language model agent"
    assert detail_data["data"]["result"]["run_id"] == run_id
    assert detail_data["data"]["result"]["topic"] == "large language model agent"

    report_response = client.post(f"/api/workflow/{run_id}/report")

    assert report_response.status_code == 200
    report_data = report_response.json()
    assert report_data["success"] is True
    assert report_data["report_path"]
    assert Path(report_data["report_path"]).is_file()
    assert str(report_dir) in report_data["report_path"]
    assert report_data["report_markdown"]
    assert "Research Workflow Report" in report_data["report_markdown"]
    assert "## RAG 索引结果" in report_data["report_markdown"]
    assert "当前 RAG 索引结果基于 dry_run 模式生成" in report_data["report_markdown"]
    assert "当前报告基于 dry_run 模式生成" in report_data["report_markdown"]

    get_report_response = client.get(f"/api/workflow/{run_id}/report")

    assert get_report_response.status_code == 200
    get_report_data = get_report_response.json()
    assert get_report_data["success"] is True
    assert get_report_data["report_markdown"]

    agent_latest_response = client.post(
        "/api/agent/query",
        json={
            "user_id": "closed-loop-user",
            "session_id": "closed-loop-session",
            "message": "查看最近一次研究闭环结果",
        },
    )

    assert agent_latest_response.status_code == 200
    agent_latest_data = agent_latest_response.json()
    assert agent_latest_data["success"] is True
    assert agent_latest_data["chosen_tool"] == "get_latest_workflow"
    assert agent_latest_data["final_answer"].strip()

    agent_report_response = client.post(
        "/api/agent/query",
        json={
            "user_id": "closed-loop-user",
            "session_id": "closed-loop-session",
            "message": "把最近一次研究闭环生成报告",
        },
    )

    assert agent_report_response.status_code == 200
    agent_report_data = agent_report_response.json()
    assert agent_report_data["success"] is True
    assert agent_report_data["chosen_tool"] == "generate_workflow_report"
    assert agent_report_data["final_answer"].strip()
    assert str(report_dir) in agent_report_data["data"]["report_path"]
