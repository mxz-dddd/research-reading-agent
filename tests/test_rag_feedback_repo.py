from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import database
from app.repositories.rag_feedback_repo import RagFeedbackRepository


@pytest.fixture()
def feedback_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagFeedbackRepository:
    test_db = tmp_path / "rag_feedback_repo.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagFeedbackRepository()


def test_rag_feedback_repo_create_and_latest(feedback_repo: RagFeedbackRepository) -> None:
    first = feedback_repo.create_feedback(
        trace_id="trace_1",
        relevance_label="irrelevant",
        expected_terms=["agent"],
        notes="first",
    )
    second = feedback_repo.create_feedback(
        trace_id="trace_1",
        relevance_label="relevant",
        expected_terms=["agent", "planning"],
        notes="latest",
    )

    latest = feedback_repo.get_latest_feedback_for_trace("trace_1")

    assert first.feedback_id
    assert second.feedback_id
    assert latest is not None
    assert latest.feedback_id == second.feedback_id
    assert latest.expected_terms == ["agent", "planning"]


def test_rag_feedback_repo_list_feedback(feedback_repo: RagFeedbackRepository) -> None:
    feedback_repo.create_feedback(trace_id="trace_1", relevance_label="relevant")
    feedback_repo.create_feedback(trace_id="trace_2", relevance_label="irrelevant")

    items = feedback_repo.list_feedback(limit=10)
    by_trace = feedback_repo.list_feedback_by_trace("trace_1")

    assert len(items) == 2
    assert len(by_trace) == 1
    assert by_trace[0].trace_id == "trace_1"


def test_rag_feedback_repo_summarize_feedback_uses_latest_label(
    feedback_repo: RagFeedbackRepository,
) -> None:
    feedback_repo.create_feedback(trace_id="trace_1", relevance_label="irrelevant")
    feedback_repo.create_feedback(trace_id="trace_1", relevance_label="relevant")
    feedback_repo.create_feedback(trace_id="trace_2", relevance_label="partially_relevant")
    feedback_repo.create_feedback(trace_id="trace_3", relevance_label="no_evidence_correct")

    summary = feedback_repo.summarize_feedback()

    assert summary["total_feedback"] == 3
    assert summary["relevant_count"] == 1
    assert summary["partially_relevant_count"] == 1
    assert summary["irrelevant_count"] == 0
    assert summary["no_evidence_correct_count"] == 1
    assert summary["relevance_rate"] == pytest.approx(2 / 3)
    assert summary["no_evidence_accuracy"] == 1.0
