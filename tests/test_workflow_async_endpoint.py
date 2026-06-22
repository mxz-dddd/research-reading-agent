from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import routes_workflow
from app.main import app
from app.schemas.workflow import ResearchWorkflowResponse
from app.services.workflow_job_service import WorkflowJobStore


@pytest.fixture(autouse=True)
def isolated_job_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_workflow, "workflow_job_store", WorkflowJobStore())


def _fake_response(topic: str, *, success: bool = True) -> ResearchWorkflowResponse:
    return ResearchWorkflowResponse(
        run_id="run_fake_1",
        success=success,
        topic=topic,
        steps=[],
        searched_papers=[],
        accepted_papers=[],
        ingested_papers=[],
        rag_indexed_papers=[],
        warnings=[],
        error=None if success else "boom",
    )


_PAYLOAD = {
    "topic": "large language model agent",
    "max_results": 3,
    "accept_top_k": 2,
    "dry_run": True,
    "index_rag": False,
}


def test_run_async_returns_job_and_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(payload: Any) -> ResearchWorkflowResponse:
        return _fake_response(payload.topic)

    monkeypatch.setattr(routes_workflow.workflow_service, "run", fake_run)
    client = TestClient(app)

    response = client.post("/api/workflow/run-async", json=_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    job_id = body["job_id"]

    # TestClient 会在响应返回前执行 background tasks，这里 job 应已完成。
    status_response = client.get(f"/api/workflow/jobs/{job_id}")
    assert status_response.status_code == 200
    job = status_response.json()["job"]
    assert job["status"] == "completed"
    assert job["run_id"] == "run_fake_1"
    assert job["error"] is None


def test_run_async_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(payload: Any) -> ResearchWorkflowResponse:
        raise RuntimeError("workflow exploded")

    monkeypatch.setattr(routes_workflow.workflow_service, "run", fake_run)
    client = TestClient(app)

    response = client.post("/api/workflow/run-async", json=_PAYLOAD)
    job_id = response.json()["job_id"]

    job = client.get(f"/api/workflow/jobs/{job_id}").json()["job"]
    assert job["status"] == "failed"
    assert "workflow exploded" in job["error"]


def test_run_async_records_unsuccessful_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(payload: Any) -> ResearchWorkflowResponse:
        return _fake_response(payload.topic, success=False)

    monkeypatch.setattr(routes_workflow.workflow_service, "run", fake_run)
    client = TestClient(app)

    response = client.post("/api/workflow/run-async", json=_PAYLOAD)
    job_id = response.json()["job_id"]

    job = client.get(f"/api/workflow/jobs/{job_id}").json()["job"]
    assert job["status"] == "failed"
    assert job["run_id"] == "run_fake_1"
    assert job["error"] == "boom"


def test_get_unknown_job_returns_404() -> None:
    client = TestClient(app)
    response = client.get("/api/workflow/jobs/job_does_not_exist")
    assert response.status_code == 404
