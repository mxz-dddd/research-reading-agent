import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.rag_quality_eval_service import GoldenQuery, RagQualityEvalService


def _golden() -> GoldenQuery:
    return GoldenQuery(query_id="q1", query="方法是什么", must_contain_any=["方法"])


def _answer_response(answer: str, answer_mode: str, chunk_ids: list[str]) -> dict:
    return {
        "answer": answer,
        "answer_mode": answer_mode,
        "evidence_chunks": [
            {"chunk_id": chunk_id, "paper_id": "1", "content": "evidence"}
            for chunk_id in chunk_ids
        ],
        "context_pack_id": "cp1",
        "pipeline": {"retrieval_mode": "hybrid"},
    }


def test_llm_answer_faithful_citations() -> None:
    service = RagQualityEvalService()
    response = _answer_response("方法是 X [chunk:c1]，结论是 Y [chunk:c2]。", "llm", ["c1", "c2"])

    result = service.evaluate_answer_response(_golden(), response)

    faith = result["citation_faithfulness"]
    assert result["answer_mode"] == "llm"
    assert faith["faithful"] is True
    assert faith["citation_precision"] == 1.0
    assert faith["invalid_cited_chunk_ids"] == []


def test_llm_answer_with_hallucinated_citation() -> None:
    service = RagQualityEvalService()
    response = _answer_response("方法 [chunk:c1]，幻觉 [chunk:ghost]。", "llm", ["c1"])

    result = service.evaluate_answer_response(_golden(), response)

    faith = result["citation_faithfulness"]
    assert faith["faithful"] is False
    assert faith["invalid_cited_chunk_ids"] == ["ghost"]
    assert faith["citation_precision"] == 0.5


def test_llm_answer_without_citations_not_faithful() -> None:
    service = RagQualityEvalService()
    response = _answer_response("方法是 X，没有引用。", "llm", ["c1"])

    result = service.evaluate_answer_response(_golden(), response)

    faith = result["citation_faithfulness"]
    assert faith["faithful"] is False
    assert faith["has_citation"] is False


def test_template_answer_skips_citation_faithfulness() -> None:
    service = RagQualityEvalService()
    response = _answer_response("模板回答，方法相关。", "template", ["c1"])

    result = service.evaluate_answer_response(_golden(), response)

    assert result["answer_mode"] == "template"
    assert result["citation_faithfulness"] is None


def test_summary_includes_citation_metrics() -> None:
    service = RagQualityEvalService()
    golden = _golden()
    search_response = {
        "evidence_chunks": [{"chunk_id": "c1", "paper_id": "1", "content": "方法"}],
        "context_pack_id": "cp1",
        "pipeline": {},
    }
    result = service.evaluate_search_response(golden, search_response, retrieval_mode="hybrid", top_k=5)
    service.evaluate_answer_response(
        golden,
        _answer_response("方法 [chunk:c1]。", "llm", ["c1"]),
        result,
    )

    summary = service.summarize_results([result])

    assert summary["llm_answer_rate"] == 1.0
    assert summary["citation_faithful_rate"] == 1.0
    assert summary["avg_citation_precision"] == 1.0
