import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api import routes_workflow
from app.main import app
from app.schemas.workflow import ResearchWorkflowResponse, ResearchWorkflowStep


def test_workflow_endpoint_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_payloads: list[Any] = []

    def fake_run(payload: Any) -> ResearchWorkflowResponse:
        seen_payloads.append(payload)
        return ResearchWorkflowResponse(
            success=True,
            topic=payload.topic,
            steps=[
                ResearchWorkflowStep(
                    step="search_papers",
                    success=True,
                    summary="fake search",
                    data={"count": 1},
                    error=None,
                )
            ],
            searched_papers=[{"id": 1, "title": "Fake Paper"}],
            accepted_papers=[{"id": 1, "title": "Fake Paper"}],
            ingested_papers=[],
            rag_indexed_papers=[],
            knowledge=None,
            innovation=None,
            warnings=[],
            error=None,
        )

    monkeypatch.setattr(routes_workflow.workflow_service, "run", fake_run)
    client = TestClient(app)

    response = client.post(
        "/api/workflow/run",
        json={
            "topic": "large language model agent",
            "max_results": 5,
            "accept_top_k": 2,
            "ingest": True,
            "index_rag": True,
            "rag_chunk_size": 600,
            "rag_chunk_overlap": 80,
            "generate_knowledge": True,
            "generate_innovation": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["topic"] == "large language model agent"
    assert data["steps"][0]["step"] == "search_papers"
    assert data["searched_papers"]
    assert "accepted_papers" in data
    assert seen_payloads[0].index_rag is True
    assert seen_payloads[0].rag_chunk_size == 600
    assert seen_payloads[0].rag_chunk_overlap == 80
    assert "warnings" in data
    assert data["error"] is None


def test_workflow_endpoint_supports_dry_run_without_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_workflow.workflow_service.workflow_repo, "create", lambda payload: None)
    client = TestClient(app)

    response = client.post(
        "/api/workflow/run",
        json={
            "topic": "large language model agent",
            "max_results": 3,
            "accept_top_k": 2,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["topic"] == "large language model agent"
    assert [step["step"] for step in data["steps"]] == [
        "search_papers",
        "accept_top_k",
        "ingest_papers",
        "index_rag",
        "generate_knowledge",
        "generate_innovation",
    ]
    assert len(data["searched_papers"]) == 3
    assert len(data["accepted_papers"]) == 2
    assert len(data["rag_indexed_papers"]) == 2
    assert data["knowledge"]["dry_run"] is True
    assert data["innovation"]["dry_run"] is True
    assert any("dry_run 模式" in warning for warning in data["warnings"])
    assert data["error"] is None
