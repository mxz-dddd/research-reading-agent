from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.rag_quality_eval_service import GoldenQuery, RagQualityEvalService, RetrievalEvalResult


def test_load_golden_queries_reads_jsonl_defaults(tmp_path: Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text('{"query_id":"gq-1","query":"What is the method?","paper_id":12}\n', encoding="utf-8")

    queries = RagQualityEvalService().load_golden_queries(path)

    assert len(queries) == 1
    assert queries[0].query_id == "gq-1"
    assert queries[0].paper_id == "12"
    assert queries[0].expected_terms == []
    assert queries[0].must_contain_any == []


def test_load_golden_queries_bad_json_reports_line_number(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"query_id":"ok","query":"ok"}\n{bad json}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="行号：2"):
        RagQualityEvalService().load_golden_queries(path)


def test_evaluate_search_response_matches_expected_terms_from_chunks() -> None:
    golden = GoldenQuery(
        query_id="gq-1",
        query="method",
        expected_terms=["method", "approach", "missing"],
    )
    response = {
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "paper_id": "paper-1",
                "content": "The proposed method uses a retrieval approach.",
                "section_title": "Methods",
            }
        ],
        "context_pack_id": "ctx-1",
        "pipeline": {"retrieval_mode": "hybrid"},
    }

    result = RagQualityEvalService().evaluate_search_response(golden, response, retrieval_mode="hybrid", top_k=5)

    assert result.matched_expected_terms == ["method", "approach"]
    assert result.missing_expected_terms == ["missing"]
    assert result.recall_expected_terms == pytest.approx(2 / 3)
    assert result.context_pack_id == "ctx-1"
    assert result.pipeline == {"retrieval_mode": "hybrid"}


def test_evaluate_search_response_matches_chunk_and_paper_ids() -> None:
    golden = GoldenQuery(
        query_id="gq-1",
        query="evidence",
        expected_chunk_ids=["chunk-1", "chunk-2"],
        expected_paper_ids=["paper-1", "paper-2"],
    )
    response = {"items": [{"chunk_id": "chunk-1", "paper_id": "paper-1", "content_preview": "evidence"}]}

    result = RagQualityEvalService().evaluate_search_response(golden, response, retrieval_mode="keyword", top_k=3)

    assert result.matched_expected_chunk_ids == ["chunk-1"]
    assert result.missing_expected_chunk_ids == ["chunk-2"]
    assert result.matched_expected_paper_ids == ["paper-1"]
    assert result.missing_expected_paper_ids == ["paper-2"]
    assert result.recall_expected_chunk_ids == 0.5
    assert result.recall_expected_paper_ids == 0.5


def test_evaluate_search_response_empty_expected_lists_have_full_recall() -> None:
    golden = GoldenQuery(query_id="gq-1", query="anything")

    result = RagQualityEvalService().evaluate_search_response(golden, {}, retrieval_mode="hybrid", top_k=5)

    assert result.recall_expected_terms == 1.0
    assert result.recall_expected_chunk_ids == 1.0
    assert result.recall_expected_paper_ids == 1.0


def test_evaluate_answer_response_checks_must_contain_any() -> None:
    service = RagQualityEvalService()
    golden = GoldenQuery(query_id="gq-1", query="answer", must_contain_any=["method", "approach"])
    retrieval_result = service.evaluate_search_response(golden, {}, retrieval_mode="hybrid", top_k=5)

    updated = service.evaluate_answer_response(golden, {"answer": "This paper describes a method."}, retrieval_result)

    assert isinstance(updated, RetrievalEvalResult)
    assert updated.answer_contains_any is True


def test_summarize_results_empty_list() -> None:
    summary = RagQualityEvalService().summarize_results([])

    assert summary["total"] == 0
    assert summary["error_count"] == 0
    assert summary["by_retrieval_mode"] == {}


def test_summarize_results_groups_by_retrieval_mode() -> None:
    service = RagQualityEvalService()
    hybrid = service.evaluate_search_response(
        GoldenQuery(query_id="gq-1", query="method", expected_terms=["method"]),
        {"chunks": [{"content": "method"}]},
        retrieval_mode="hybrid",
        top_k=5,
    )
    keyword = service.evaluate_search_response(
        GoldenQuery(query_id="gq-2", query="method", expected_terms=["missing"]),
        {"chunks": [{"content": "method"}]},
        retrieval_mode="keyword",
        top_k=5,
    )
    keyword.answer_contains_any = False

    summary = service.summarize_results([hybrid, keyword])

    assert summary["total"] == 2
    assert summary["avg_recall_expected_terms"] == 0.5
    assert summary["by_retrieval_mode"]["hybrid"]["total"] == 1
    assert summary["by_retrieval_mode"]["keyword"]["total"] == 1
    assert summary["by_retrieval_mode"]["keyword"]["answer_contains_any_rate"] == 0.0
