"""Optional Chroma adapter loaded only when explicitly configured."""

import importlib
from typing import Any


class ChromaVectorStore:
    name = "chroma"

    def __init__(self, persist_directory: str = "data/chroma") -> None:
        try:
            chromadb = importlib.import_module("chromadb")
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is not installed. Install the optional dependency with: "
                "pip install -r requirements-paperweave-chroma.txt"
            ) from exc
        self._client = chromadb.PersistentClient(path=persist_directory)

    def _collection(self, provider_key: str) -> Any:
        safe_name = (
            "pw_"
            + "".join(character if character.isalnum() else "_" for character in provider_key)[:60]
        )
        return self._client.get_or_create_collection(name=safe_name)

    def get_vectors(self, chunk_ids: list[str], provider_key: str) -> dict[str, list[float]]:
        if not chunk_ids:
            return {}
        data = self._collection(provider_key).get(ids=chunk_ids, include=["embeddings"])
        result: dict[str, list[float]] = {}
        for chunk_id, vector in zip(
            data.get("ids", []), data.get("embeddings") or [], strict=False
        ):
            if vector is not None:
                result[chunk_id] = [float(value) for value in vector]
        return result

    def upsert_vectors(
        self,
        provider_key: str,
        items: list[tuple[str, list[float]]],
    ) -> None:
        if not items:
            return
        self._collection(provider_key).upsert(
            ids=[chunk_id for chunk_id, _vector in items],
            embeddings=[vector for _chunk_id, vector in items],
        )
