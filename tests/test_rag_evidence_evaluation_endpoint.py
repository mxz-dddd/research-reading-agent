from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import routes_rag
from app.main import app
from app.schemas.rag import RagEvidenceFeedbackRead


def fake_feedback() -> RagEvidenceFeedbackRead:
    return RagEvidenceFeedbackRead(
        id=1,
        evidence_feedback_id="evidence_feedback_test_1",
        trace_id="trace_test_1",
        chunk_id="chunk_test_1",
        rank=1,
        relevance_score=2,
        relevance_label="relevant",
        notes="good",
        created_at="2026-01-01T00:00:00Z",
    )


def test_add_rag_evidence_feedback_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_add(**kwargs: Any) -> dict[str, Any]:
        return {"success": True, "data": fake_feedback(), "message": None, "error": None}

    monkeypatch.setattr(routes_rag.rag_evaluation_service, "add_evidence_feedback", fake_add)
    client = TestClient(app)

    response = client.post(
        "/api/rag/traces/trace_test_1/evidence-feedback",
        json={"chunk_id": "chunk_test_1", "rank": 1, "relevance_score": 2, "notes": "good"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["evidence_feedback_id"] == "evidence_feedback_test_1"


def test_rag_evidence_evaluation_summary_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_rag.rag_evaluation_service,
        "get_evidence_evaluation_summary",
        lambda trace_id=None: {
            "success": True,
            "summary": {
                "total_traces_with_evidence_feedback": 2,
                "total_evidence_feedback": 3,
                "recall_at_1": 0.5,
                "recall_at_3": 1.0,
                "recall_at_5": 1.0,
                "mrr": 0.75,
                "ndcg_at_5": 0.8,
            },
            "message": None,
        },
    )
    client = TestClient(app)

    response = client.get("/api/rag/evaluation/evidence-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["summary"]["mrr"] == 0.75


def test_rag_trace_evidence_evaluation_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_rag.rag_evaluation_service,
        "get_trace_evidence_evaluation",
        lambda trace_id: {
            "success": True,
            "trace_id": trace_id,
            "evidence": [
                {
                    "rank": 1,
                    "chunk_id": "chunk_test_1",
                    "score": 2,
                    "latest_feedback": fake_feedback().model_dump(),
                }
            ],
            "message": None,
            "error": None,
        },
    )
    client = TestClient(app)

    response = client.get("/api/rag/evaluation/traces/trace_test_1/evidence")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["evidence"][0]["latest_feedback"]["relevance_label"] == "relevant"
