from types import SimpleNamespace

import pytest

from app.rag.chroma_vector_store import ChromaVectorStore
from app.rag.retrievers import HybridRetriever


class FakeCollection:
    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}

    def get(self, *, ids: list[str], include: list[str]) -> dict:
        assert include == ["embeddings"]
        found_ids = [chunk_id for chunk_id in ids if chunk_id in self.vectors]
        return {
            "ids": found_ids,
            "embeddings": [self.vectors[chunk_id] for chunk_id in found_ids],
        }

    def upsert(self, *, ids: list[str], embeddings: list[list[float]]) -> None:
        self.vectors.update(dict(zip(ids, embeddings)))


class FakePersistentClient:
    last_path: str | None = None

    def __init__(self, *, path: str) -> None:
        type(self).last_path = path
        self.collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(self, *, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def test_chroma_adapter_uses_dynamic_import(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = SimpleNamespace(PersistentClient=FakePersistentClient)
    monkeypatch.setattr(
        "app.rag.chroma_vector_store.importlib.import_module",
        lambda name: fake_module if name == "chromadb" else None,
    )

    store = ChromaVectorStore(persist_directory="tmp/chroma-test")
    store.upsert_vectors("hash:hash:2", [("c1", [1.0, 0.0])])

    assert FakePersistentClient.last_path == "tmp/chroma-test"
    assert store.get_vectors(["c1", "missing"], "hash:hash:2") == {
        "c1": [1.0, 0.0]
    }


def test_chroma_adapter_missing_dependency_has_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_import_error(name: str):
        raise ImportError(name)

    monkeypatch.setattr(
        "app.rag.chroma_vector_store.importlib.import_module",
        raise_import_error,
    )

    with pytest.raises(RuntimeError, match="requirements-paperweave-chroma.txt"):
        ChromaVectorStore()


def test_default_retriever_does_not_import_chromadb(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(name: str):
        if name == "chromadb":
            raise AssertionError("default vector-store mode must not import chromadb")
        raise ImportError(name)

    monkeypatch.setattr("importlib.import_module", fail_import)
    settings = SimpleNamespace(
        rag_embedding_provider="hash",
        rag_embedding_dim=16,
        rag_rrf_k=60,
        rag_rerank_enabled=True,
        rag_vector_store="none",
    )

    retriever = HybridRetriever(SimpleNamespace(), settings)

    assert retriever.vector_store is None


def test_retriever_builds_chroma_only_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = SimpleNamespace(PersistentClient=FakePersistentClient)
    monkeypatch.setattr(
        "app.rag.chroma_vector_store.importlib.import_module",
        lambda name: fake_module if name == "chromadb" else None,
    )
    settings = SimpleNamespace(
        rag_embedding_provider="hash",
        rag_embedding_dim=16,
        rag_rrf_k=60,
        rag_rerank_enabled=True,
        rag_vector_store="chroma",
        rag_chroma_persist_directory="tmp/explicit-chroma",
    )

    retriever = HybridRetriever(SimpleNamespace(), settings)

    assert isinstance(retriever.vector_store, ChromaVectorStore)
    assert FakePersistentClient.last_path == "tmp/explicit-chroma"
