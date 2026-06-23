from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import database
from app.repositories.rag_trace_repo import RagTraceRepository
from app.schemas.rag import RagTraceCreate
from app.services.rag_evaluation_service import RagEvaluationService


@pytest.fixture()
def eval_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagEvaluationService:
    test_db = tmp_path / "rag_evidence_eval.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagEvaluationService()


def create_trace(trace_id: str = "trace_eval_1") -> None:
    RagTraceRepository().create_trace(
        RagTraceCreate(
            trace_id=trace_id,
            query="retrieval agent",
            mode="answer",
            paper_id="12",
            top_k=5,
            hit_count=2,
            no_evidence=False,
            answer="fake answer",
            evidence=[
                {"chunk_id": f"{trace_id}_chunk_1", "score": 3, "content_preview": "first"},
                {"chunk_id": f"{trace_id}_chunk_2", "score": 2, "content_preview": "second"},
            ],
            metadata={"source": "test"},
        )
    )


def test_evidence_evaluation_service_adds_feedback_by_rank(
    eval_service: RagEvaluationService,
) -> None:
    create_trace()

    result = eval_service.add_evidence_feedback(
        trace_id="trace_eval_1",
        rank=1,
        relevance_score=2,
        notes="direct evidence",
    )

    assert result["success"] is True
    assert result["data"].chunk_id == "trace_eval_1_chunk_1"
    assert result["data"].relevance_label == "relevant"


def test_evidence_evaluation_service_rejects_chunk_not_in_trace(
    eval_service: RagEvaluationService,
) -> None:
    create_trace()

    result = eval_service.add_evidence_feedback(
        trace_id="trace_eval_1",
        chunk_id="missing_chunk",
        relevance_score=2,
    )

    assert result["success"] is False
    assert result["error"] == "chunk not found in trace"


def test_evidence_evaluation_service_summary_metrics(eval_service: RagEvaluationService) -> None:
    create_trace("trace_eval_1")
    create_trace("trace_eval_2")
    eval_service.add_evidence_feedback(trace_id="trace_eval_1", rank=1, relevance_score=0)
    eval_service.add_evidence_feedback(trace_id="trace_eval_1", rank=2, relevance_score=2)
    eval_service.add_evidence_feedback(trace_id="trace_eval_2", rank=1, relevance_score=1)

    result = eval_service.get_evidence_evaluation_summary()
    summary = result["summary"]

    assert result["success"] is True
    assert summary["total_traces_with_evidence_feedback"] == 2
    assert summary["total_evidence_feedback"] == 3
    assert summary["recall_at_1"] == pytest.approx(0.5)
    assert summary["recall_at_3"] == pytest.approx(1.0)
    assert summary["recall_at_5"] == pytest.approx(1.0)
    assert summary["mrr"] == pytest.approx(0.75)
    assert summary["ndcg_at_5"] > 0


def test_evidence_evaluation_service_summary_without_feedback(
    eval_service: RagEvaluationService,
) -> None:
    result = eval_service.get_evidence_evaluation_summary()

    assert result["success"] is True
    assert result["summary"]["total_evidence_feedback"] == 0
    assert result["summary"]["recall_at_1"] == 0.0
    assert "暂无 evidence-level feedback" in result["message"]


def test_evidence_evaluation_service_trace_detail(eval_service: RagEvaluationService) -> None:
    create_trace()
    eval_service.add_evidence_feedback(trace_id="trace_eval_1", rank=1, relevance_score=2)

    result = eval_service.get_trace_evidence_evaluation("trace_eval_1")

    assert result["success"] is True
    assert result["evidence"][0]["latest_feedback"]["relevance_label"] == "relevant"
    assert result["evidence"][1]["latest_feedback"] is None
