import pytest
from fastapi.testclient import TestClient

from app.api import routes_workflow
from app.main import app
from app.schemas.workflow import WorkflowRunDetail, WorkflowRunSummary


def fake_workflow_detail(run_id: str = "run-001") -> WorkflowRunDetail:
    return WorkflowRunDetail(
        id=1,
        run_id=run_id,
        topic="large language model agent",
        success=True,
        dry_run=True,
        max_results=3,
        accept_top_k=2,
        searched_count=3,
        accepted_count=2,
        ingested_count=2,
        knowledge_generated=True,
        innovation_generated=True,
        warnings=["dry_run warning"],
        error=None,
        created_at="2026-06-04T00:00:00+00:00",
        result={"run_id": run_id, "success": True, "dry_run": True},
    )


def fake_workflow_summary(run_id: str = "run-001") -> WorkflowRunSummary:
    detail = fake_workflow_detail(run_id)
    return WorkflowRunSummary(**detail.model_dump(exclude={"result"}))


def test_get_latest_workflow_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_workflow.workflow_service, "latest_workflow", lambda: fake_workflow_detail()
    )
    client = TestClient(app)

    response = client.get("/api/workflow/latest")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["run_id"] == "run-001"
    assert data["data"]["dry_run"] is True


def test_get_latest_workflow_endpoint_returns_structured_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routes_workflow.workflow_service, "latest_workflow", lambda: None)
    client = TestClient(app)

    response = client.get("/api/workflow/latest")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["data"] is None
    assert "还没有" in data["message"]


def test_list_workflow_history_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_limits: list[int] = []

    def fake_history(limit: int = 10) -> list[WorkflowRunSummary]:
        seen_limits.append(limit)
        return [fake_workflow_summary("run-002")]

    monkeypatch.setattr(routes_workflow.workflow_service, "list_workflow_history", fake_history)
    client = TestClient(app)

    response = client.get("/api/workflow/history?limit=1")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert seen_limits == [1]
    assert data["items"][0]["run_id"] == "run-002"
    assert "result" not in data["items"][0]


def test_get_workflow_detail_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_workflow.workflow_service,
        "get_workflow_detail",
        lambda run_id: fake_workflow_detail(run_id),
    )
    client = TestClient(app)

    response = client.get("/api/workflow/run-003")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["run_id"] == "run-003"
    assert data["data"]["result"]["run_id"] == "run-003"
