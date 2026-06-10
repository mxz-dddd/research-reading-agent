from __future__ import annotations

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
from app.schemas.rag import RagAnswerResponse, RagIndexResponse, RagSearchChunk, RagSearchResponse


def test_rag_index_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_index(**kwargs: Any) -> RagIndexResponse:
        return RagIndexResponse(success=True, paper_id=kwargs["paper_id"], chunk_count=2, warnings=[], error=None)

    monkeypatch.setattr(routes_rag.rag_service, "index_paper_for_rag", fake_index)
    client = TestClient(app)

    response = client.post("/api/rag/index", json={"paper_id": "12", "chunk_size": 800, "chunk_overlap": 120})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["paper_id"] == "12"
    assert data["chunk_count"] == 2


def test_rag_search_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(**kwargs: Any) -> RagSearchResponse:
        return RagSearchResponse(
            success=True,
            query=kwargs["query"],
            evidence_chunks=[
                RagSearchChunk(
                    score=2,
                    chunk_id="chunk-1",
                    paper_id="12",
                    chunk_index=0,
                    matched_terms=["error", "propagation"],
                    content="Propagation error correction",
                    content_preview="Propagation error correction",
                    source_path="fake.txt",
                    metadata={},
                    score_reason="命中 2 个查询词：error, propagation",
                )
            ],
        )

    monkeypatch.setattr(routes_rag.rag_service, "search_rag", fake_search)
    client = TestClient(app)

    response = client.post("/api/rag/search", json={"query": "propagation error", "top_k": 5, "paper_id": "12"})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["evidence_chunks"][0]["chunk_id"] == "chunk-1"
    assert data["evidence_chunks"][0]["matched_terms"] == ["error", "propagation"]
    assert "命中 2 个查询词" in data["evidence_chunks"][0]["score_reason"]


def test_rag_answer_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_answer(**kwargs: Any) -> RagAnswerResponse:
        return RagAnswerResponse(
            success=True,
            query=kwargs["query"],
            answer="根据检索到的片段，可能与 propagation error 有关。",
            evidence_chunks=[],
            warning="RAG v1 warning",
        )

    monkeypatch.setattr(routes_rag.rag_service, "answer_with_rag", fake_answer)
    client = TestClient(app)

    response = client.post("/api/rag/answer", json={"query": "main contribution", "top_k": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["answer"]


def test_rag_answer_endpoint_empty_query_returns_structured_failure() -> None:
    client = TestClient(app)

    response = client.post("/api/rag/answer", json={"query": "", "top_k": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["no_evidence"] is True
    assert data["error"] == "empty query"
    assert "query 为空" in data["answer"]
