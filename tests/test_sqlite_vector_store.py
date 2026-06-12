from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import database
from app.rag.retrievers import HybridRetriever
from app.rag.sqlite_vector_store import SqliteVectorStore, build_provider_key
from app.repositories.rag_repo import RagChunkRepository
from app.schemas.rag import RagChunkCreate


@pytest.fixture()
def test_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "vector_store.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(db_path)))
    database.init_db()
    return db_path


def test_sqlite_vector_store_roundtrip(test_db: Path) -> None:
    store = SqliteVectorStore()
    store.upsert_vectors("hash:hash:2", [("c1", [1.0, 0.0]), ("c2", [0.0, 1.0])])

    assert store.get_vectors(["c1", "c2", "missing"], "hash:hash:2") == {
        "c1": [1.0, 0.0],
        "c2": [0.0, 1.0],
    }


def test_sqlite_vector_store_upsert_and_provider_isolation(test_db: Path) -> None:
    store = SqliteVectorStore()
    store.upsert_vectors("provider-a", [("c1", [1.0])])
    store.upsert_vectors("provider-a", [("c1", [2.0])])

    assert store.get_vectors(["c1"], "provider-a") == {"c1": [2.0]}
    assert store.get_vectors(["c1"], "provider-b") == {}


def test_sqlite_vector_store_delete(test_db: Path) -> None:
    store = SqliteVectorStore()
    store.upsert_vectors("key", [("c1", [1.0]), ("c2", [2.0])])
    store.delete_by_chunk_ids(["c1"])

    assert store.get_vectors(["c1", "c2"], "key") == {"c2": [2.0]}


def test_build_provider_key() -> None:
    assert build_provider_key(
        {"embedding_provider": "hash", "embedding_model": "hash", "embedding_dim": 256}
    ) == "hash:hash:256"


def test_hybrid_retriever_reuses_sqlite_cache(test_db: Path) -> None:
    repo = RagChunkRepository()
    for chunk_id, content in (("A", "propagation error"), ("B", "vision transformer")):
        repo.create_chunk(
            RagChunkCreate(
                chunk_id=chunk_id,
                paper_id="1",
                source_type="test",
                chunk_index=0,
                content=content,
                content_preview=content,
                content_for_embedding=content,
            )
        )
    settings = SimpleNamespace(
        rag_embedding_provider="hash",
        rag_embedding_dim=32,
        rag_rrf_k=60,
        rag_rerank_enabled=True,
        rag_vector_store="sqlite",
    )

    _first, first_pipeline = HybridRetriever(repo, settings).search("propagation", top_k=2)
    _second, second_pipeline = HybridRetriever(repo, settings).search("propagation", top_k=2)

    assert first_pipeline["vector_store"] == "sqlite"
    assert first_pipeline["embedding_cache"]["computed"] == 2
    assert first_pipeline["embedding_cache"]["cache_hits"] == 0
    assert second_pipeline["embedding_cache"]["computed"] == 0
    assert second_pipeline["embedding_cache"]["cache_hits"] == 2


def test_hybrid_retriever_default_keeps_cache_disabled(test_db: Path) -> None:
    repo = RagChunkRepository()
    repo.create_chunk(
        RagChunkCreate(
            chunk_id="A",
            paper_id="1",
            source_type="test",
            chunk_index=0,
            content="local evidence",
            content_preview="local evidence",
            content_for_embedding="local evidence",
        )
    )
    settings = SimpleNamespace(
        rag_embedding_provider="hash",
        rag_embedding_dim=16,
        rag_rrf_k=60,
        rag_rerank_enabled=True,
    )

    _results, pipeline = HybridRetriever(repo, settings).search("local", top_k=1)

    assert pipeline["vector_store"] == "none"
    assert pipeline["embedding_cache"]["cache_hits"] == 0
