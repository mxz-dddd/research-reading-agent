from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import database
from app.schemas.paper import PaperRead
from app.services.rag_service import RAG_V1_WARNING, RAG_V2_WARNING, RagService


@pytest.fixture()
def rag_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagService:
    test_db = tmp_path / "rag_service.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagService()


def fake_paper(local_text_path: str | None) -> PaperRead:
    return PaperRead(
        id=12,
        topic_id=None,
        title="Fake RAG Paper",
        authors="Test Author",
        abstract="This paper studies propagation error and correction methods.",
        url="https://example.com/paper",
        source="mock",
        published_at="2026-01-01",
        summary=None,
        screening_summary="screening",
        relevance_score=4,
        worth_reading="值得继续看",
        is_accepted=1,
        accepted_at=None,
        pdf_url=None,
        local_pdf_path=None,
        local_text_path=local_text_path,
        local_summary_path=None,
        abstract_summary=None,
        deep_summary=None,
        ingest_status="pdf_text",
        status="ingested",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def test_rag_service_splits_text(rag_service: RagService) -> None:
    chunks = rag_service._split_text("a" * 250, chunk_size=100, chunk_overlap=20)

    assert len(chunks) == 3
    assert all(chunks)


def test_rag_service_indexes_paper_for_rag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rag_service: RagService,
) -> None:
    text_path = tmp_path / "paper.txt"
    text_path.write_text("Propagation error correction method. " * 20, encoding="utf-8")
    monkeypatch.setattr(rag_service.paper_repo, "get", lambda paper_id: fake_paper(str(text_path)))

    result = rag_service.index_paper_for_rag("12", chunk_size=120, chunk_overlap=20)

    assert result.success is True
    assert result.paper_id == "12"
    assert result.chunk_count > 1
    assert rag_service.rag_repo.list_chunks_by_paper_id("12")


def test_rag_service_search_and_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rag_service: RagService,
) -> None:
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "The main contribution is propagation error correction for timing systems.",
        encoding="utf-8",
    )
    monkeypatch.setattr(rag_service.paper_repo, "get", lambda paper_id: fake_paper(str(text_path)))
    rag_service.index_paper_for_rag("12", chunk_size=200, chunk_overlap=20)

    search_result = rag_service.search_rag("propagation error", top_k=3)
    answer_result = rag_service.answer_with_rag("main contribution", top_k=3)

    assert search_result.success is True
    assert search_result.evidence_chunks
    assert search_result.evidence_chunks[0].matched_terms
    assert search_result.evidence_chunks[0].score_reason
    assert search_result.trace_id
    assert rag_service.get_trace_detail(search_result.trace_id) is not None
    assert answer_result.success is True
    assert answer_result.evidence_chunks
    assert "[Evidence 1]" in answer_result.answer
    assert "以下回答基于 contextual hybrid RAG 检索到的 evidence" in answer_result.answer
    assert "retrieval_scores=" in answer_result.answer
    assert answer_result.warning == RAG_V2_WARNING
    assert answer_result.context_pack_id
    assert answer_result.retrieval_mode == "hybrid"
    assert answer_result.pipeline["retrieval_mode"] == "hybrid"
    assert answer_result.trace_id
    answer_trace = rag_service.get_trace_detail(answer_result.trace_id)
    assert answer_trace is not None
    assert answer_trace.mode == "answer"
    assert answer_trace.answer is not None
    assert answer_trace.metadata["retrieval_mode"] == "hybrid"
    assert answer_trace.metadata["context_pack_id"] == answer_result.context_pack_id
    assert answer_trace.metadata["pipeline"]["retrieval_mode"] == "hybrid"


def test_rag_service_keyword_mode_still_works(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rag_service: RagService,
) -> None:
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Keyword retrieval keeps propagation error matching available.", encoding="utf-8"
    )
    monkeypatch.setattr(rag_service.paper_repo, "get", lambda paper_id: fake_paper(str(text_path)))
    rag_service.index_paper_for_rag("12", chunk_size=200, chunk_overlap=20)

    result = rag_service.answer_with_rag("propagation error", top_k=3, retrieval_mode="keyword")

    assert result.success is True
    assert result.evidence_chunks
    assert result.warning == RAG_V1_WARNING
    assert result.retrieval_mode == "keyword"
    assert result.pipeline["retrieval_mode"] == "keyword"


def test_rag_service_answer_without_evidence(rag_service: RagService) -> None:
    result = rag_service.answer_with_rag("nonexistent query", top_k=3)

    assert result.success is True
    assert result.evidence_chunks == []
    assert result.no_evidence is True
    assert "没有检索到足够证据" in result.answer
    assert result.warning == RAG_V2_WARNING
    assert result.context_pack_id
    assert result.pipeline["retrieval_mode"] == "hybrid"
    assert result.trace_id
    trace = rag_service.get_trace_detail(result.trace_id)
    assert trace is not None
    assert trace.no_evidence is True
    assert trace.hit_count == 0
    assert trace.metadata["context_pack_id"] == result.context_pack_id


def test_rag_service_handles_empty_query(rag_service: RagService) -> None:
    search_result = rag_service.search_rag("   ", top_k=3)
    answer_result = rag_service.answer_with_rag("", top_k=3)

    assert search_result.success is False
    assert search_result.no_evidence is True
    assert search_result.error == "empty query"
    assert "query 为空" in (search_result.message or "")
    assert answer_result.success is False
    assert answer_result.no_evidence is True
    assert answer_result.error == "empty query"
    assert "query 为空" in answer_result.answer
    assert search_result.trace_id is None
    assert answer_result.trace_id is None


def test_rag_service_can_disable_trace_saving(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rag_service: RagService,
) -> None:
    text_path = tmp_path / "paper.txt"
    text_path.write_text("Retrieval augmented generation uses evidence chunks.", encoding="utf-8")
    monkeypatch.setattr(rag_service.paper_repo, "get", lambda paper_id: fake_paper(str(text_path)))
    rag_service.index_paper_for_rag("12", chunk_size=200, chunk_overlap=20)

    search_result = rag_service.search_rag("retrieval generation", save_trace=False)
    answer_result = rag_service.answer_with_rag("retrieval generation", save_trace=False)

    assert search_result.trace_id is None
    assert answer_result.trace_id is None
    assert rag_service.get_latest_traces(limit=10) == []
