import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.repositories.rag_evidence_feedback_repo import RagEvidenceFeedbackRepository


@pytest.fixture()
def evidence_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagEvidenceFeedbackRepository:
    test_db = tmp_path / "rag_evidence_feedback_repo.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagEvidenceFeedbackRepository()


def test_rag_evidence_feedback_repo_create_and_latest(evidence_repo: RagEvidenceFeedbackRepository) -> None:
    first = evidence_repo.create_evidence_feedback(
        trace_id="trace_1",
        chunk_id="chunk_1",
        rank=1,
        relevance_score=0,
    )
    second = evidence_repo.create_evidence_feedback(
        trace_id="trace_1",
        chunk_id="chunk_1",
        rank=1,
        relevance_score=2,
        notes="latest",
    )

    latest = evidence_repo.get_latest_feedback_for_evidence(trace_id="trace_1", chunk_id="chunk_1")

    assert first.evidence_feedback_id
    assert second.evidence_feedback_id
    assert latest is not None
    assert latest.evidence_feedback_id == second.evidence_feedback_id
    assert latest.relevance_label == "relevant"


def test_rag_evidence_feedback_repo_list_by_trace(evidence_repo: RagEvidenceFeedbackRepository) -> None:
    evidence_repo.create_evidence_feedback(trace_id="trace_1", chunk_id="chunk_1", rank=1, relevance_score=2)
    evidence_repo.create_evidence_feedback(trace_id="trace_1", chunk_id="chunk_2", rank=2, relevance_score=1)
    evidence_repo.create_evidence_feedback(trace_id="trace_2", chunk_id="chunk_3", rank=1, relevance_score=0)

    items = evidence_repo.list_feedback_by_trace("trace_1")

    assert len(items) == 2
    assert {item.chunk_id for item in items} == {"chunk_1", "chunk_2"}


def test_rag_evidence_feedback_repo_summarize_uses_latest(evidence_repo: RagEvidenceFeedbackRepository) -> None:
    evidence_repo.create_evidence_feedback(trace_id="trace_1", chunk_id="chunk_1", rank=1, relevance_score=0)
    evidence_repo.create_evidence_feedback(trace_id="trace_1", chunk_id="chunk_1", rank=1, relevance_score=2)
    evidence_repo.create_evidence_feedback(trace_id="trace_1", chunk_id="chunk_2", rank=2, relevance_score=1)

    summary = evidence_repo.summarize_evidence_feedback()

    assert summary["total_traces_with_evidence_feedback"] == 1
    assert summary["total_evidence_feedback"] == 2
    assert summary["relevant_evidence_count"] == 1
    assert summary["partially_relevant_evidence_count"] == 1
    assert summary["irrelevant_evidence_count"] == 0
