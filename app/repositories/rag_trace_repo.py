from __future__ import annotations

from datetime import datetime, timezone
import json
from sqlite3 import Row

from app.core.database import get_connection
from app.schemas.rag import RagTraceCreate, RagTraceRead


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_trace(row: Row) -> RagTraceRead:
    data = dict(row)
    data["no_evidence"] = bool(data["no_evidence"])
    data["evidence"] = json.loads(data.pop("evidence_json"))
    data["metadata"] = json.loads(data.pop("metadata_json"))
    return RagTraceRead(**data)


class RagTraceRepository:
    def create_trace(self, payload: RagTraceCreate) -> RagTraceRead:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rag_traces (
                    trace_id, query, mode, paper_id, top_k, hit_count,
                    no_evidence, answer, evidence_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.trace_id,
                    payload.query,
                    payload.mode,
                    payload.paper_id,
                    payload.top_k,
                    payload.hit_count,
                    1 if payload.no_evidence else 0,
                    payload.answer,
                    json.dumps(payload.evidence, ensure_ascii=False),
                    json.dumps(payload.metadata, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM rag_traces WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_trace(row)

    def get_by_trace_id(self, trace_id: str) -> RagTraceRead | None:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM rag_traces WHERE trace_id = ?", (trace_id,)).fetchone()
        return _row_to_trace(row) if row else None

    def get_latest(self, limit: int = 10) -> list[RagTraceRead]:
        safe_limit = max(1, min(limit, 100))
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rag_traces ORDER BY created_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [_row_to_trace(row) for row in rows]

    def list_by_paper_id(self, paper_id: str, limit: int = 10) -> list[RagTraceRead]:
        safe_limit = max(1, min(limit, 100))
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rag_traces
                WHERE paper_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (str(paper_id), safe_limit),
            ).fetchall()
        return [_row_to_trace(row) for row in rows]

    def summarize_traces(self) -> dict[str, int]:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_traces,
                    SUM(CASE WHEN mode = 'answer' THEN 1 ELSE 0 END) AS answered_traces,
                    SUM(CASE WHEN no_evidence = 1 THEN 1 ELSE 0 END) AS no_evidence_traces
                FROM rag_traces
                """
            ).fetchone()
        return {
            "total_traces": int(row["total_traces"] or 0),
            "answered_traces": int(row["answered_traces"] or 0),
            "no_evidence_traces": int(row["no_evidence_traces"] or 0),
        }
