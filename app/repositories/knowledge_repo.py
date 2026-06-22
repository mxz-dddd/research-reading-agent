from __future__ import annotations

from datetime import UTC, datetime
from sqlite3 import Row

from fastapi import HTTPException

from app.core.database import get_connection
from app.schemas.knowledge import KnowledgeArtifactCreate, KnowledgeArtifactRead


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_artifact(row: Row) -> KnowledgeArtifactRead:
    return KnowledgeArtifactRead(**dict(row))


class KnowledgeRepository:
    def create(self, payload: KnowledgeArtifactCreate) -> KnowledgeArtifactRead:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_artifacts (
                    topic, source_paper_count, knowledge_tree_markdown,
                    learning_roadmap_markdown, mermaid_mindmap, mermaid_flowchart,
                    local_markdown_path, generation_method, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.topic,
                    payload.source_paper_count,
                    payload.knowledge_tree_markdown,
                    payload.learning_roadmap_markdown,
                    payload.mermaid_mindmap,
                    payload.mermaid_flowchart,
                    payload.local_markdown_path,
                    payload.generation_method,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM knowledge_artifacts WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_artifact(row)

    def latest(self) -> KnowledgeArtifactRead:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_artifacts ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="还没有生成过知识树")
        return _row_to_artifact(row)

    def list(self) -> list[KnowledgeArtifactRead]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_artifacts ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_artifact(row) for row in rows]
