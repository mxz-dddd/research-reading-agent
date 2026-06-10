from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.repositories.rag_trace_repo import RagTraceRepository
from app.schemas.rag import RagTraceCreate


@pytest.fixture()
def trace_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagTraceRepository:
    test_db = tmp_path / "rag_trace_repo.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagTraceRepository()


def sample_trace(trace_id: str = "trace_test_1", paper_id: str | None = "12") -> RagTraceCreate:
    return RagTraceCreate(
        trace_id=trace_id,
        query="propagation error",
        mode="search",
        paper_id=paper_id,
        top_k=5,
        hit_count=1,
        no_evidence=False,
        answer=None,
        evidence=[{"chunk_id": "chunk-1", "paper_id": paper_id, "score": 2}],
        metadata={"score_summary": {"max_score": 2}},
    )


def test_rag_trace_repo_create_and_get(trace_repo: RagTraceRepository) -> None:
    created = trace_repo.create_trace(sample_trace())

    found = trace_repo.get_by_trace_id("trace_test_1")

    assert created.trace_id == "trace_test_1"
    assert found is not None
    assert found.trace_id == "trace_test_1"
    assert found.evidence[0]["chunk_id"] == "chunk-1"
    assert found.metadata["score_summary"]["max_score"] == 2


def test_rag_trace_repo_get_latest(trace_repo: RagTraceRepository) -> None:
    trace_repo.create_trace(sample_trace("trace_test_1"))
    trace_repo.create_trace(sample_trace("trace_test_2"))

    traces = trace_repo.get_latest(limit=1)

    assert len(traces) == 1
    assert traces[0].trace_id == "trace_test_2"


def test_rag_trace_repo_list_by_paper_id(trace_repo: RagTraceRepository) -> None:
    trace_repo.create_trace(sample_trace("trace_p12", paper_id="12"))
    trace_repo.create_trace(sample_trace("trace_p13", paper_id="13"))

    traces = trace_repo.list_by_paper_id("12", limit=10)

    assert len(traces) == 1
    assert traces[0].trace_id == "trace_p12"
