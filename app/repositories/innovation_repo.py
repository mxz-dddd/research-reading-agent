from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlite3 import Row

from app.core.database import get_connection
from app.core.exceptions import NotFoundError
from app.schemas.innovation import InnovationArtifactCreate, InnovationArtifactRead


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_artifact(row: Row) -> InnovationArtifactRead:
    data = dict(row)
    data["innovation_json"] = json.loads(data["innovation_json"])
    return InnovationArtifactRead(**data)


class InnovationRepository:
    def create(self, payload: InnovationArtifactCreate) -> InnovationArtifactRead:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO innovation_artifacts (
                    topic, source_paper_count, innovation_markdown, innovation_json,
                    summary_markdown, generation_method, local_markdown_path,
                    local_json_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.topic,
                    payload.source_paper_count,
                    payload.innovation_markdown,
                    json.dumps(payload.innovation_json, ensure_ascii=False),
                    payload.summary_markdown,
                    payload.generation_method,
                    payload.local_markdown_path,
                    payload.local_json_path,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM innovation_artifacts WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_artifact(row)

    def latest(self) -> InnovationArtifactRead:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM innovation_artifacts ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise NotFoundError("还没有生成过创新点分析")
        return _row_to_artifact(row)

    def list_all(self) -> list[InnovationArtifactRead]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM innovation_artifacts ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_artifact(row) for row in rows]
