import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.repositories.rag_repo import RagChunkRepository
from app.schemas.rag import RagChunkCreate


@pytest.fixture()
def rag_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagChunkRepository:
    test_db = tmp_path / "rag_repo.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagChunkRepository()


def sample_chunk(chunk_id: str = "chunk-1", content: str = "Propagation error correction method") -> RagChunkCreate:
    return RagChunkCreate(
        chunk_id=chunk_id,
        paper_id="12",
        source_type="local_text",
        source_path="fake.txt",
        chunk_index=0,
        content=content,
        content_preview=content[:50],
        metadata={"paper_title": "Fake Paper"},
    )


def test_rag_repo_create_and_list_chunks(rag_repo: RagChunkRepository) -> None:
    created = rag_repo.create_chunk(sample_chunk())

    chunks = rag_repo.list_chunks_by_paper_id("12")

    assert created.chunk_id == "chunk-1"
    assert len(chunks) == 1
    assert chunks[0].metadata["paper_title"] == "Fake Paper"
    assert chunks[0].chunker_version == "contextual_v1"
    assert chunks[0].index_version == "hybrid_v2"


def test_rag_repo_create_and_search_contextual_fields(rag_repo: RagChunkRepository) -> None:
    payload = sample_chunk("chunk-context", "Timing systems use correction.")
    payload.contextual_header = "Paper: Fake Paper\nSection: Propagation Error\nChunk: 0\nSource: local_text"
    payload.section_title = "Propagation Error"
    payload.content_for_embedding = payload.contextual_header + "\n" + payload.content
    payload.token_count = 12

    created = rag_repo.create_chunk(payload)
    listed = rag_repo.list_all_chunks("12")
    results = rag_repo.search_chunks("propagation error", top_k=5)

    assert created.section_title == "Propagation Error"
    assert listed[0].content_for_embedding
    assert listed[0].token_count == 12
    assert results[0].chunk_id == "chunk-context"
    assert results[0].section_title == "Propagation Error"
    assert results[0].contextual_header
    assert results[0].retrieval_scores["sparse"] > 0


def test_rag_repo_search_chunks(rag_repo: RagChunkRepository) -> None:
    rag_repo.create_chunk(sample_chunk("chunk-1", "Propagation error correction method for timing"))
    rag_repo.create_chunk(sample_chunk("chunk-2", "Unrelated vision transformer discussion"))

    results = rag_repo.search_chunks("propagation error", top_k=5)

    assert len(results) == 1
    assert results[0].chunk_id == "chunk-1"
    assert results[0].score > 0
    assert results[0].chunk_index == 0
    assert results[0].source_path == "fake.txt"
    assert results[0].matched_terms == ["error", "propagation"]
    assert "命中 2 个查询词" in (results[0].score_reason or "")


def test_rag_repo_delete_chunks_by_paper_id(rag_repo: RagChunkRepository) -> None:
    rag_repo.create_chunk(sample_chunk("chunk-1"))
    rag_repo.create_chunk(sample_chunk("chunk-2"))

    deleted = rag_repo.delete_chunks_by_paper_id("12")

    assert deleted == 2
    assert rag_repo.list_chunks_by_paper_id("12") == []
