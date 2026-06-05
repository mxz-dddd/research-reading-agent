import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api import routes_rag
from app.main import app
from app.schemas.rag import RagTraceFeedbackRead, RagTraceRead


def fake_feedback() -> RagTraceFeedbackRead:
    return RagTraceFeedbackRead(
        id=1,
        feedback_id="feedback_test_1",
        trace_id="trace_test_1",
        relevance_label="relevant",
        expected_terms=["retrieval"],
        notes="good",
        created_at="2026-01-01T00:00:00Z",
    )


def fake_trace() -> RagTraceRead:
    return RagTraceRead(
        id=1,
        trace_id="trace_test_1",
        query="retrieval agent",
        mode="answer",
        paper_id="12",
        top_k=5,
        hit_count=1,
        no_evidence=False,
        answer="fake answer",
        evidence=[{"chunk_id": "chunk-1"}],
        metadata={"source": "test"},
        created_at="2026-01-01T00:00:00Z",
    )


def test_add_rag_trace_feedback_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_add(**kwargs: Any) -> dict[str, Any]:
        return {"success": True, "data": fake_feedback(), "message": None, "error": None}

    monkeypatch.setattr(routes_rag.rag_evaluation_service, "add_trace_feedback", fake_add)
    client = TestClient(app)

    response = client.post(
        "/api/rag/traces/trace_test_1/feedback",
        json={
            "relevance_label": "relevant",
            "expected_terms": ["retrieval"],
            "notes": "good",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["feedback_id"] == "feedback_test_1"


def test_rag_evaluation_summary_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_rag.rag_evaluation_service,
        "get_rag_evaluation_summary",
        lambda: {
            "success": True,
            "summary": {
                "total_traces": 2,
                "answered_traces": 1,
                "no_evidence_traces": 1,
                "total_feedback": 1,
                "relevance_rate": 1.0,
                "no_evidence_accuracy": None,
                "label_distribution": {"relevant": 1},
            },
        },
    )
    client = TestClient(app)

    response = client.get("/api/rag/evaluation/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["summary"]["total_traces"] == 2


def test_rag_trace_evaluation_detail_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_rag.rag_evaluation_service,
        "get_trace_evaluation_detail",
        lambda trace_id: {
            "success": True,
            "trace": fake_trace(),
            "latest_feedback": fake_feedback(),
            "message": None,
            "error": None,
        },
    )
    client = TestClient(app)

    response = client.get("/api/rag/evaluation/traces/trace_test_1")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["trace"]["trace_id"] == "trace_test_1"
    assert data["latest_feedback"]["relevance_label"] == "relevant"
