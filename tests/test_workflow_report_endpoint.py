import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api import routes_workflow
from app.main import app
from app.schemas.workflow import WorkflowReportResponse


def fake_report(run_id: str) -> WorkflowReportResponse:
    return WorkflowReportResponse(
        success=True,
        run_id=run_id,
        report_path=f"data/archives/workflow_reports/workflow_report_{run_id}.md",
        report_markdown="# Research Workflow Report\n\nfake report",
        error=None,
    )


def test_generate_workflow_report_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_workflow.workflow_report_service, "generate_report", fake_report)
    client = TestClient(app)

    response = client.post("/api/workflow/run_report_001/report")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["run_id"] == "run_report_001"
    assert data["report_path"].endswith("workflow_report_run_report_001.md")
    assert "# Research Workflow Report" in data["report_markdown"]
    assert data["error"] is None


def test_get_workflow_report_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_workflow.workflow_report_service, "get_report", fake_report)
    client = TestClient(app)

    response = client.get("/api/workflow/run_report_001/report")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["run_id"] == "run_report_001"
    assert data["report_markdown"].startswith("# Research Workflow Report")
