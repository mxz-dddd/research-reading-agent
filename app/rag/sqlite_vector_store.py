"""Optional SQLite-backed embedding cache for PaperWeave."""

from datetime import datetime, timezone
import json
from typing import Any

from app.core.database import get_connection


class SqliteVectorStore:
    name = "sqlite"

    def get_vectors(self, chunk_ids: list[str], provider_key: str) -> dict[str, list[float]]:
        if not chunk_ids:
            return {}
        result: dict[str, list[float]] = {}
        with get_connection() as conn:
            for start in range(0, len(chunk_ids), 500):
                batch = chunk_ids[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT chunk_id, vector_json FROM rag_embeddings "
                    f"WHERE provider_key = ? AND chunk_id IN ({placeholders})",
                    [provider_key, *batch],
                ).fetchall()
                for row in rows:
                    try:
                        vector = json.loads(row["vector_json"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(vector, list):
                        result[row["chunk_id"]] = [float(value) for value in vector]
        return result

    def upsert_vectors(
        self,
        provider_key: str,
        items: list[tuple[str, list[float]]],
    ) -> None:
        if not items:
            return
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO rag_embeddings (chunk_id, provider_key, dim, vector_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id, provider_key) DO UPDATE SET
                    dim = excluded.dim,
                    vector_json = excluded.vector_json,
                    created_at = excluded.created_at
                """,
                [
                    (chunk_id, provider_key, len(vector), json.dumps(vector), now)
                    for chunk_id, vector in items
                ],
            )
            conn.commit()

    def delete_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        with get_connection() as conn:
            for start in range(0, len(chunk_ids), 500):
                batch = chunk_ids[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                conn.execute(
                    f"DELETE FROM rag_embeddings WHERE chunk_id IN ({placeholders})",
                    batch,
                )
            conn.commit()


def build_provider_key(metadata: dict[str, Any]) -> str:
    provider = metadata.get("embedding_provider") or "unknown"
    model = metadata.get("embedding_model") or "unknown"
    dim = metadata.get("embedding_dim") or "?"
    return f"{provider}:{model}:{dim}"
