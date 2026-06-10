from __future__ import annotations

import hashlib
import math
import re


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text)
        if token.strip()
    ]


class HashEmbeddingProvider:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.md5(token.encode("utf-8"), usedforsecurity=False).hexdigest()
            vector[int(digest, 16) % self.dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def get_embedding_provider(provider: str = "hash", dim: int = 256) -> HashEmbeddingProvider:
    if provider != "hash":
        raise ValueError("当前只支持 hash embedding provider")
    return HashEmbeddingProvider(dim=dim)
