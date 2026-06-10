from __future__ import annotations

from datetime import datetime, timezone
from sqlite3 import Row
from uuid import uuid4

from app.core.database import get_connection
from app.schemas.rag import RagEvidenceFeedbackRead


RAG_EVIDENCE_LABEL_BY_SCORE = {
    0: "irrelevant",
    1: "partially_relevant",
    2: "relevant",
}

RAG_EVIDENCE_SCORE_BY_LABEL = {
    "irrelevant": 0,
    "partially_relevant": 1,
    "relevant": 2,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_feedback(row: Row) -> RagEvidenceFeedbackRead:
    return RagEvidenceFeedbackRead(**dict(row))


class RagEvidenceFeedbackRepository:
    def create_evidence_feedback(
        self,
        *,
        trace_id: str,
        chunk_id: str,
        rank: int,
        relevance_score: int,
        relevance_label: str | None = None,
        notes: str | None = None,
    ) -> RagEvidenceFeedbackRead:
        normalized_label = relevance_label or RAG_EVIDENCE_LABEL_BY_SCORE[relevance_score]
        evidence_feedback_id = f"evidence_feedback_{uuid4().hex[:12]}"
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rag_evidence_feedback (
                    evidence_feedback_id, trace_id, chunk_id, rank,
                    relevance_score, relevance_label, notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_feedback_id,
                    trace_id,
                    chunk_id,
                    rank,
                    relevance_score,
                    normalized_label,
                    notes,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM rag_evidence_feedback WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_feedback(row)

    def get_latest_feedback_for_evidence(
        self,
        *,
        trace_id: str,
        chunk_id: str,
    ) -> RagEvidenceFeedbackRead | None:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM rag_evidence_feedback
                WHERE trace_id = ? AND chunk_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (trace_id, chunk_id),
            ).fetchone()
        return _row_to_feedback(row) if row else None

    def list_feedback_by_trace(self, trace_id: str) -> list[RagEvidenceFeedbackRead]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rag_evidence_feedback
                WHERE trace_id = ?
                ORDER BY rank ASC, created_at DESC, id DESC
                """,
                (trace_id,),
            ).fetchall()
        return [_row_to_feedback(row) for row in rows]

    def summarize_evidence_feedback(self, trace_id: str | None = None) -> dict[str, object]:
        latest_by_evidence = self._latest_feedback_by_evidence(trace_id=trace_id)
        total = len(latest_by_evidence)
        relevant_count = sum(1 for item in latest_by_evidence.values() if item.relevance_score == 2)
        partially_relevant_count = sum(1 for item in latest_by_evidence.values() if item.relevance_score == 1)
        irrelevant_count = sum(1 for item in latest_by_evidence.values() if item.relevance_score == 0)
        trace_ids = {item.trace_id for item in latest_by_evidence.values()}
        return {
            "total_traces_with_evidence_feedback": len(trace_ids),
            "total_evidence_feedback": total,
            "relevant_evidence_count": relevant_count,
            "partially_relevant_evidence_count": partially_relevant_count,
            "irrelevant_evidence_count": irrelevant_count,
        }

    def latest_feedback_by_evidence(
        self,
        trace_id: str | None = None,
    ) -> dict[tuple[str, str], RagEvidenceFeedbackRead]:
        return self._latest_feedback_by_evidence(trace_id=trace_id)

    def _latest_feedback_by_evidence(
        self,
        trace_id: str | None = None,
    ) -> dict[tuple[str, str], RagEvidenceFeedbackRead]:
        params: tuple[str, ...] = ()
        where = ""
        if trace_id is not None:
            where = "WHERE trace_id = ?"
            params = (trace_id,)

        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM rag_evidence_feedback
                {where}
                ORDER BY trace_id ASC, chunk_id ASC, created_at DESC, id DESC
                """,
                params,
            ).fetchall()

        latest: dict[tuple[str, str], RagEvidenceFeedbackRead] = {}
        for row in rows:
            feedback = _row_to_feedback(row)
            latest.setdefault((feedback.trace_id, feedback.chunk_id), feedback)
        return latest
