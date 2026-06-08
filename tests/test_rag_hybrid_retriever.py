import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.rag.retrievers import HybridRetriever
from app.repositories.rag_repo import RagChunkRepository
from app.schemas.rag import RagChunkCreate


@pytest.fixture()
def rag_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagChunkRepository:
    test_db = tmp_path / "hybrid_retriever.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return RagChunkRepository()


def make_chunk(
    chunk_id: str,
    content: str,
    *,
    section_title: str | None = None,
    header: str | None = None,
) -> RagChunkCreate:
    contextual_header = header or f"Paper: Test\nSection: {section_title or 'Unknown'}\nChunk: 0\nSource: test"
    return RagChunkCreate(
        chunk_id=chunk_id,
        paper_id="12",
        source_type="test",
        chunk_index=0,
        content=content,
        content_preview=content,
        metadata={"paper_title": "Test"},
        contextual_header=contextual_header,
        section_title=section_title,
        content_for_embedding=f"{contextual_header}\n{content}",
        token_count=20,
    )


def test_hybrid_retriever_fuses_dense_sparse_and_reranks(rag_repo: RagChunkRepository) -> None:
    rag_repo.create_chunk(make_chunk("A", "Propagation error correction appears as exact evidence."))
    rag_repo.create_chunk(
        make_chunk(
            "B",
            "Timing systems need robust mitigation.",
            section_title="Propagation Error",
        )
    )
    rag_repo.create_chunk(make_chunk("C", "Unrelated vision transformer discussion."))
    settings = SimpleNamespace(
        rag_embedding_provider="hash",
        rag_embedding_dim=256,
        rag_rrf_k=60,
        rag_rerank_enabled=True,
    )

    results, pipeline = HybridRetriever(rag_repo, settings).search("propagation error", top_k=2)
    ids = [item.chunk_id for item in results]

    assert "A" in ids
    assert "B" in ids
    assert "C" not in ids
    assert all(item.retrieval_scores["rrf"] > 0 for item in results)
    assert all(item.rerank_score is not None for item in results)
    assert pipeline["sparse_candidate_count"] >= 1
    assert pipeline["dense_candidate_count"] >= 1
    assert pipeline["fused_candidate_count"] >= 2
    assert pipeline["rerank_enabled"] is True
