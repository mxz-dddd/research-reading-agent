from datetime import datetime, timezone
import json
from sqlite3 import Row
from uuid import uuid4

from app.core.database import get_connection
from app.schemas.rag import RagTraceFeedbackRead


RAG_RELEVANCE_LABELS = {
    "relevant",
    "partially_relevant",
    "irrelevant",
    "no_evidence_correct",
    "no_evidence_incorrect",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_feedback(row: Row) -> RagTraceFeedbackRead:
    data = dict(row)
    data["expected_terms"] = json.loads(data.pop("expected_terms_json"))
    return RagTraceFeedbackRead(**data)


class RagFeedbackRepository:
    def create_feedback(
        self,
        *,
        trace_id: str,
        relevance_label: str,
        expected_terms: list[str] | None = None,
        notes: str | None = None,
    ) -> RagTraceFeedbackRead:
        feedback_id = f"feedback_{uuid4().hex[:12]}"
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rag_trace_feedback (
                    feedback_id, trace_id, relevance_label,
                    expected_terms_json, notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    trace_id,
                    relevance_label,
                    json.dumps(expected_terms or [], ensure_ascii=False),
                    notes,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM rag_trace_feedback WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_feedback(row)

    def get_latest_feedback_for_trace(self, trace_id: str) -> RagTraceFeedbackRead | None:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM rag_trace_feedback
                WHERE trace_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (trace_id,),
            ).fetchone()
        return _row_to_feedback(row) if row else None

    def list_feedback(self, limit: int = 50) -> list[RagTraceFeedbackRead]:
        safe_limit = max(1, min(limit, 200))
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rag_trace_feedback
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [_row_to_feedback(row) for row in rows]

    def list_feedback_by_trace(self, trace_id: str) -> list[RagTraceFeedbackRead]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rag_trace_feedback
                WHERE trace_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (trace_id,),
            ).fetchall()
        return [_row_to_feedback(row) for row in rows]

    def summarize_feedback(self) -> dict[str, object]:
        latest_by_trace: dict[str, RagTraceFeedbackRead] = {}
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rag_trace_feedback
                ORDER BY trace_id ASC, created_at DESC, id DESC
                """
            ).fetchall()

        for row in rows:
            feedback = _row_to_feedback(row)
            latest_by_trace.setdefault(feedback.trace_id, feedback)

        distribution = {label: 0 for label in RAG_RELEVANCE_LABELS}
        for feedback in latest_by_trace.values():
            distribution[feedback.relevance_label] = distribution.get(feedback.relevance_label, 0) + 1

        total = len(latest_by_trace)
        relevant_count = distribution.get("relevant", 0)
        partially_relevant_count = distribution.get("partially_relevant", 0)
        irrelevant_count = distribution.get("irrelevant", 0)
        no_evidence_correct_count = distribution.get("no_evidence_correct", 0)
        no_evidence_incorrect_count = distribution.get("no_evidence_incorrect", 0)
        relevance_rate = (relevant_count + partially_relevant_count) / total if total else 0.0
        no_evidence_total = no_evidence_correct_count + no_evidence_incorrect_count
        no_evidence_accuracy = (
            no_evidence_correct_count / no_evidence_total
            if no_evidence_total
            else None
        )
        return {
            "total_feedback": total,
            "relevant_count": relevant_count,
            "partially_relevant_count": partially_relevant_count,
            "irrelevant_count": irrelevant_count,
            "no_evidence_correct_count": no_evidence_correct_count,
            "no_evidence_incorrect_count": no_evidence_incorrect_count,
            "relevance_rate": relevance_rate,
            "no_evidence_accuracy": no_evidence_accuracy,
            "label_distribution": distribution,
        }
