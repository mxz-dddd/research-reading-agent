from __future__ import annotations

from datetime import datetime, timezone
import json
from sqlite3 import Row

from fastapi import HTTPException

from app.core.database import get_connection
from app.schemas.workflow import WorkflowRunCreate, WorkflowRunDetail, WorkflowRunSummary


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_summary(row: Row) -> WorkflowRunSummary:
    data = dict(row)
    data["success"] = bool(data["success"])
    data["dry_run"] = bool(data["dry_run"])
    data["knowledge_generated"] = bool(data["knowledge_generated"])
    data["innovation_generated"] = bool(data["innovation_generated"])
    data["warnings"] = json.loads(data.pop("warnings_json"))
    data.pop("result_json", None)
    return WorkflowRunSummary(**data)


def _row_to_detail(row: Row) -> WorkflowRunDetail:
    data = dict(row)
    data["success"] = bool(data["success"])
    data["dry_run"] = bool(data["dry_run"])
    data["knowledge_generated"] = bool(data["knowledge_generated"])
    data["innovation_generated"] = bool(data["innovation_generated"])
    data["warnings"] = json.loads(data.pop("warnings_json"))
    data["result"] = json.loads(data.pop("result_json"))
    return WorkflowRunDetail(**data)


class WorkflowRunRepository:
    def create(self, payload: WorkflowRunCreate) -> WorkflowRunDetail:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, topic, success, dry_run, max_results, accept_top_k,
                    searched_count, accepted_count, ingested_count,
                    knowledge_generated, innovation_generated, warnings_json,
                    result_json, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.run_id,
                    payload.topic,
                    int(payload.success),
                    int(payload.dry_run),
                    payload.max_results,
                    payload.accept_top_k,
                    payload.searched_count,
                    payload.accepted_count,
                    payload.ingested_count,
                    int(payload.knowledge_generated),
                    int(payload.innovation_generated),
                    json.dumps(payload.warnings, ensure_ascii=False),
                    json.dumps(payload.result, ensure_ascii=False),
                    payload.error,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_detail(row)

    def latest(self) -> WorkflowRunDetail | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return _row_to_detail(row)

    def list(self, limit: int = 10) -> list[WorkflowRunSummary]:
        safe_limit = max(1, min(limit, 100))
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs ORDER BY created_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [_row_to_summary(row) for row in rows]

    def get_by_run_id(self, run_id: str) -> WorkflowRunDetail:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="workflow run 不存在")
        return _row_to_detail(row)
