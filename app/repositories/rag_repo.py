from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from sqlite3 import Row

from app.core.database import get_connection
from app.schemas.rag import RagChunkCreate, RagChunkRead, RagSearchChunk


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_chunk(row: Row) -> RagChunkRead:
    data = dict(row)
    data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    return RagChunkRead(**data)


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text)
        if token.strip()
    }


def _preview(text: str, max_chars: int = 240) -> str:
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


class RagChunkRepository:
    def create_chunk(self, payload: RagChunkCreate) -> RagChunkRead:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rag_chunks (
                    chunk_id, paper_id, source_type, source_path, chunk_index,
                    content, content_preview, metadata_json, contextual_header,
                    section_title, content_for_embedding, token_count,
                    chunker_version, index_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.chunk_id,
                    payload.paper_id,
                    payload.source_type,
                    payload.source_path,
                    payload.chunk_index,
                    payload.content,
                    payload.content_preview,
                    json.dumps(payload.metadata, ensure_ascii=False),
                    payload.contextual_header,
                    payload.section_title,
                    payload.content_for_embedding,
                    payload.token_count,
                    payload.chunker_version,
                    payload.index_version,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM rag_chunks WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_chunk(row)

    def delete_chunks_by_paper_id(self, paper_id: str) -> int:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM rag_chunks WHERE paper_id = ?", (str(paper_id),))
            conn.commit()
        return cursor.rowcount

    def list_chunks_by_paper_id(self, paper_id: str) -> list[RagChunkRead]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rag_chunks WHERE paper_id = ? ORDER BY chunk_index ASC",
                (str(paper_id),),
            ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def list_all_chunks(self, paper_id: str | None = None) -> list[RagChunkRead]:
        with get_connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM rag_chunks WHERE paper_id = ? ORDER BY paper_id ASC, chunk_index ASC",
                    (str(paper_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rag_chunks ORDER BY paper_id ASC, chunk_index ASC"
                ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def search_chunks(
        self,
        query: str,
        top_k: int = 5,
        paper_id: str | None = None,
    ) -> list[RagSearchChunk]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []

        with get_connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM rag_chunks WHERE paper_id = ?",
                    (str(paper_id),),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM rag_chunks").fetchall()

        scored: list[RagSearchChunk] = []
        query_lower = query.lower()
        for row in rows:
            chunk = _row_to_chunk(row)
            content_lower = chunk.content.lower()
            searchable_text = "\n".join(
                part
                for part in [chunk.contextual_header, chunk.section_title, chunk.content]
                if part
            )
            content_tokens = _tokens(searchable_text)
            overlap = query_tokens.intersection(content_tokens)
            phrase_bonus = 2 if query_lower in content_lower else 0
            score = float(len(overlap) + phrase_bonus)
            if score <= 0:
                continue
            matched_terms = sorted(overlap)
            score_reason = f"命中 {len(matched_terms)} 个查询词：{', '.join(matched_terms)}"
            if phrase_bonus:
                score_reason += "；包含完整查询短语"
            scored.append(
                RagSearchChunk(
                    score=score,
                    chunk_id=chunk.chunk_id,
                    paper_id=chunk.paper_id,
                    chunk_index=chunk.chunk_index,
                    matched_terms=matched_terms,
                    content=chunk.content,
                    content_preview=_preview(chunk.content_preview or chunk.content),
                    source_path=chunk.source_path,
                    metadata=chunk.metadata,
                    score_reason=score_reason,
                    retrieval_scores={"sparse": score},
                    section_title=chunk.section_title,
                    contextual_header=chunk.contextual_header,
                )
            )

        scored.sort(key=lambda item: (item.score, item.chunk_id), reverse=True)
        return scored[: max(1, min(top_k, 20))]
