from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api import routes_rag
from app.main import app
from app.schemas.rag import RagTraceRead


def fake_trace(trace_id: str = "trace_test_1", paper_id: str | None = "12") -> RagTraceRead:
    return RagTraceRead(
        id=1,
        trace_id=trace_id,
        query="propagation error",
        mode="answer",
        paper_id=paper_id,
        top_k=5,
        hit_count=1,
        no_evidence=False,
        answer="fake answer",
        evidence=[{"chunk_id": "chunk-1", "paper_id": paper_id, "score": 2}],
        metadata={"source": "test"},
        created_at="2026-01-01T00:00:00Z",
    )


def test_rag_traces_latest_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_rag.rag_service, "get_latest_traces", lambda limit=10: [fake_trace()])
    client = TestClient(app)

    response = client.get("/api/rag/traces/latest?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["items"][0]["trace_id"] == "trace_test_1"


def test_rag_trace_detail_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_rag.rag_service, "get_trace_detail", lambda trace_id: fake_trace(trace_id))
    client = TestClient(app)

    response = client.get("/api/rag/traces/trace_test_1")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["trace_id"] == "trace_test_1"


def test_rag_trace_detail_endpoint_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_rag.rag_service, "get_trace_detail", lambda trace_id: None)
    client = TestClient(app)

    response = client.get("/api/rag/traces/trace_missing")

    assert response.status_code == 404


def test_rag_traces_by_paper_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_rag.rag_service, "list_traces_by_paper", lambda paper_id, limit=10: [fake_trace(paper_id=paper_id)])
    client = TestClient(app)

    response = client.get("/api/rag/traces/by-paper/12?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["items"][0]["paper_id"] == "12"
