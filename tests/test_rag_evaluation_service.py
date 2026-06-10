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
from app.services.rag_evaluation_service import RagEvaluationService


@pytest.fixture()
def eval_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagEvaluationService:
    test_db = tmp_path / "rag_evaluation_service.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagEvaluationService()


def create_trace(trace_id: str = "trace_eval_1", *, no_evidence: bool = False) -> None:
    RagTraceRepository().create_trace(
        RagTraceCreate(
            trace_id=trace_id,
            query="retrieval agent",
            mode="answer",
            paper_id="12",
            top_k=5,
            hit_count=0 if no_evidence else 1,
            no_evidence=no_evidence,
            answer="fake answer",
            evidence=[] if no_evidence else [{"chunk_id": "chunk-1", "paper_id": "12"}],
            metadata={"source": "test"},
        )
    )


def test_rag_evaluation_service_adds_feedback_for_existing_trace(eval_service: RagEvaluationService) -> None:
    create_trace()

    result = eval_service.add_trace_feedback(
        trace_id="trace_eval_1",
        relevance_label="relevant",
        expected_terms=["retrieval"],
        notes="good evidence",
    )

    assert result["success"] is True
    assert result["data"].trace_id == "trace_eval_1"
    assert result["data"].relevance_label == "relevant"


def test_rag_evaluation_service_fails_safely_when_trace_missing(eval_service: RagEvaluationService) -> None:
    result = eval_service.add_trace_feedback(trace_id="trace_missing", relevance_label="relevant")

    assert result["success"] is False
    assert result["error"] == "trace not found"


def test_rag_evaluation_service_rejects_invalid_label(eval_service: RagEvaluationService) -> None:
    create_trace()

    result = eval_service.add_trace_feedback(trace_id="trace_eval_1", relevance_label="bad_label")

    assert result["success"] is False
    assert "allowed labels" in result["error"]


def test_rag_evaluation_service_summary_and_detail(eval_service: RagEvaluationService) -> None:
    create_trace("trace_eval_1")
    create_trace("trace_eval_2", no_evidence=True)
    eval_service.add_trace_feedback(trace_id="trace_eval_1", relevance_label="partially_relevant")
    eval_service.add_trace_feedback(trace_id="trace_eval_2", relevance_label="no_evidence_correct")

    summary = eval_service.get_rag_evaluation_summary()["summary"]
    detail = eval_service.get_trace_evaluation_detail("trace_eval_1")

    assert summary["total_traces"] == 2
    assert summary["answered_traces"] == 2
    assert summary["no_evidence_traces"] == 1
    assert summary["total_feedback"] == 2
    assert summary["label_distribution"]["partially_relevant"] == 1
    assert summary["no_evidence_accuracy"] == 1.0
    assert detail["success"] is True
    assert detail["trace"].trace_id == "trace_eval_1"
    assert detail["latest_feedback"].relevance_label == "partially_relevant"


def test_rag_evaluation_service_detail_without_feedback(eval_service: RagEvaluationService) -> None:
    create_trace()

    detail = eval_service.get_trace_evaluation_detail("trace_eval_1")

    assert detail["success"] is True
    assert detail["latest_feedback"] is None
    assert "暂无人工 feedback" in detail["message"]
