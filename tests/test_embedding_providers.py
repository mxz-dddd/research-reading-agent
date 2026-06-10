import importlib
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.embeddings import HashEmbeddingProvider, get_embedding_provider


def test_hash_embedding_provider_is_deterministic() -> None:
    provider = HashEmbeddingProvider(dim=16)

    first = provider.embed_text("PaperWeave propagation error")
    second = provider.embed_text("PaperWeave propagation error")

    assert first == second
    assert len(first) == 16
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)
    assert provider.metadata()["embedding_provider"] == "hash"
    assert provider.metadata()["embedding_model"] == "hash"
    assert provider.metadata()["embedding_dim"] == 16
    assert provider.metadata()["embedding_device"] is None


def test_hash_embedding_provider_embed_texts() -> None:
    provider = HashEmbeddingProvider(dim=8)

    vectors = provider.embed_texts(["first text", "second text"])

    assert isinstance(vectors, list)
    assert len(vectors) == 2
    assert all(isinstance(vector, list) for vector in vectors)
    assert all(len(vector) == 8 for vector in vectors)


def test_get_embedding_provider_defaults_to_hash_without_import(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(name: str):
        if name == "sentence_transformers":
            raise AssertionError("sentence_transformers should not be imported for hash provider")
        return importlib.import_module(name)

    monkeypatch.setattr("app.rag.embeddings.importlib.import_module", fail_import)

    provider = get_embedding_provider(provider=None, dim=12)

    assert isinstance(provider, HashEmbeddingProvider)
    assert provider.metadata()["embedding_provider"] == "hash"
    assert provider.metadata()["embedding_dim"] == 12


def test_get_embedding_provider_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        get_embedding_provider("unknown")


def test_sentence_transformers_provider_uses_dynamic_import(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str | None = None) -> None:
            self.model_name = model_name
            self.device = device

        def encode(
            self,
            texts,
            batch_size: int = 32,
            normalize_embeddings: bool = True,
            convert_to_numpy: bool = False,
        ):
            assert batch_size == 7
            assert normalize_embeddings is True
            assert convert_to_numpy is False
            if isinstance(texts, str):
                return [1.0, 0.0, 0.0]
            return [[1.0, 0.0, 0.0] for _text in texts]

    fake_module = SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)

    def fake_import(name: str):
        assert name == "sentence_transformers"
        return fake_module

    monkeypatch.setattr("app.rag.embeddings.importlib.import_module", fake_import)

    provider = get_embedding_provider(
        "sentence-transformers",
        model_name="fake-model",
        device="cpu",
        batch_size=7,
    )

    assert provider.embed_text("query") == [1.0, 0.0, 0.0]
    assert provider.embed_texts(["a", "b"]) == [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    assert provider.metadata()["embedding_provider"] == "sentence-transformers"
    assert provider.metadata()["embedding_model"] == "fake-model"
    assert provider.metadata()["embedding_device"] == "cpu"
    assert provider.metadata()["embedding_batch_size"] == 7
    assert provider.metadata()["embedding_dim"] == 3


def test_sentence_transformers_provider_auto_device_omits_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_kwargs = {}

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs) -> None:
            init_kwargs.update(kwargs)

        def encode(self, texts, batch_size: int, normalize_embeddings: bool, convert_to_numpy: bool):
            return [[2.0, 0.0]]

    fake_module = SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setattr(
        "app.rag.embeddings.importlib.import_module",
        lambda name: fake_module,
    )

    provider = get_embedding_provider("sentence_transformers", model_name="fake-model", device="auto")

    assert init_kwargs == {}
    assert provider.embed_text("query") == [1.0, 0.0]


def test_sentence_transformers_provider_missing_dependency_has_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_import_error(name: str):
        raise ImportError(name)

    monkeypatch.setattr("app.rag.embeddings.importlib.import_module", raise_import_error)

    with pytest.raises(RuntimeError) as exc_info:
        get_embedding_provider("sentence-transformers")

    message = str(exc_info.value)
    assert "sentence-transformers is not installed" in message
    assert "pip install sentence-transformers" in message
