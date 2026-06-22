import hashlib
import importlib
import math
import re
from typing import Any, Protocol

from app.core.config import settings


def _tokens(text: str) -> list[str]:
    return [
        token.lower() for token in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text) if token.strip()
    ]


class BaseEmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def metadata(self) -> dict[str, Any]: ...


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _as_python(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _is_vector(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and (
        not value or not isinstance(value[0], (list, tuple))
    )


def _to_float_vector(value: Any) -> list[float]:
    value = _as_python(value)
    return [float(item) for item in value]


def _to_vector_list(value: Any) -> list[list[float]]:
    value = _as_python(value)
    if value == []:
        return []
    if _is_vector(value):
        return [_l2_normalize(_to_float_vector(value))]
    return [_l2_normalize(_to_float_vector(item)) for item in value]


class HashEmbeddingProvider:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.md5(token.encode("utf-8"), usedforsecurity=False).hexdigest()
            vector[int(digest, 16) % self.dim] += 1.0
        return _l2_normalize(vector)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def metadata(self) -> dict[str, Any]:
        return {
            "embedding_provider": "hash",
            "embedding_model": "hash",
            "embedding_dim": self.dim,
            "embedding_device": None,
            "embedding_batch_size": None,
        }


class SentenceTransformersEmbeddingProvider:
    def __init__(
        self,
        *,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "auto",
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.dim: int | None = None

        try:
            module = importlib.import_module("sentence_transformers")
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install it with: pip install sentence-transformers"
            ) from exc

        model_kwargs: dict[str, Any] = {}
        if device != "auto":
            model_kwargs["device"] = device
        self.model = module.SentenceTransformer(model_name, **model_kwargs)
        if hasattr(self.model, "get_sentence_embedding_dimension"):
            dimension = self.model.get_sentence_embedding_dimension()
            self.dim = int(dimension) if dimension is not None else None

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        encoded = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=False,
        )
        vectors = _to_vector_list(encoded)
        if vectors and self.dim is None:
            self.dim = len(vectors[0])
        return vectors

    def metadata(self) -> dict[str, Any]:
        return {
            "embedding_provider": "sentence-transformers",
            "embedding_model": self.model_name,
            "embedding_dim": self.dim,
            "embedding_device": self.device,
            "embedding_batch_size": self.batch_size,
        }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def get_embedding_provider(
    provider: str | None = None,
    dim: int = 256,
    model_name: str | None = None,
    device: str | None = None,
    batch_size: int | None = None,
) -> BaseEmbeddingProvider:
    provider_name = (provider or settings.rag_embedding_provider or "hash").strip().lower()
    provider_name = provider_name.replace("_", "-")
    if provider_name == "hash":
        return HashEmbeddingProvider(dim=dim)
    if provider_name == "sentence-transformers":
        return SentenceTransformersEmbeddingProvider(
            model_name=model_name or settings.rag_sentence_transformers_model,
            device=device or settings.rag_sentence_transformers_device,
            batch_size=batch_size or settings.rag_embedding_batch_size,
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")
