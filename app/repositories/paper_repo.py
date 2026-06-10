from __future__ import annotations

from app.core.exceptions import NotFoundError

from datetime import datetime, timezone
from sqlite3 import Row


from app.core.database import get_connection
from app.schemas.paper import (
    PaperCreate,
    PaperRead,
    PaperSearchHistoryCreate,
    PaperSearchHistoryRead,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_paper(row: Row) -> PaperRead:
    return PaperRead(**dict(row))


def _row_to_search_history(row: Row) -> PaperSearchHistoryRead:
    return PaperSearchHistoryRead(**dict(row))


class PaperRepository:
    def create(self, payload: PaperCreate) -> PaperRead:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO papers (
                    topic_id, title, authors, abstract, url, source,
                    published_at, summary, screening_summary, relevance_score,
                    worth_reading, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.topic_id,
                    payload.title,
                    payload.authors,
                    payload.abstract,
                    payload.url,
                    payload.source,
                    payload.published_at,
                    payload.summary,
                    payload.screening_summary,
                    payload.relevance_score,
                    payload.worth_reading,
                    payload.status,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM papers WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_paper(row)

    def list(self, status: str | None = None) -> list[PaperRead]:
        with get_connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM papers WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
        return [_row_to_paper(row) for row in rows]

    def get(self, paper_id: int) -> PaperRead:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise NotFoundError("论文不存在")
        return _row_to_paper(row)

    def get_by_url(self, url: str) -> PaperRead | None:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM papers WHERE url = ?", (url,)).fetchone()
        if row is None:
            return None
        return _row_to_paper(row)

    def list_accepted(self) -> list[PaperRead]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE is_accepted = 1 ORDER BY accepted_at DESC"
            ).fetchall()
        return [_row_to_paper(row) for row in rows]

    def update_status(self, paper_id: int, status: str) -> PaperRead:
        now = _now()
        with get_connection() as conn:
            conn.execute(
                "UPDATE papers SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, paper_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise NotFoundError("论文不存在")
        return _row_to_paper(row)

    def accept(self, paper_id: int, pdf_url: str | None = None) -> PaperRead:
        now = _now()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE papers
                SET is_accepted = 1,
                    accepted_at = COALESCE(accepted_at, ?),
                    pdf_url = COALESCE(?, pdf_url),
                    ingest_status = COALESCE(ingest_status, 'accepted'),
                    status = 'accepted',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, pdf_url, now, paper_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise NotFoundError("论文不存在")
        return _row_to_paper(row)

    def update_ingest_result(
        self,
        paper_id: int,
        *,
        pdf_url: str | None,
        local_pdf_path: str | None,
        local_text_path: str | None,
        local_summary_path: str | None,
        abstract_summary: str,
        deep_summary: str,
        ingest_status: str,
    ) -> PaperRead:
        now = _now()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE papers
                SET pdf_url = COALESCE(?, pdf_url),
                    local_pdf_path = ?,
                    local_text_path = ?,
                    local_summary_path = ?,
                    abstract_summary = ?,
                    deep_summary = ?,
                    ingest_status = ?,
                    status = 'ingested',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    pdf_url,
                    local_pdf_path,
                    local_text_path,
                    local_summary_path,
                    abstract_summary,
                    deep_summary,
                    ingest_status,
                    now,
                    paper_id,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise NotFoundError("论文不存在")
        return _row_to_paper(row)

    def create_search_history(
        self,
        payload: PaperSearchHistoryCreate,
    ) -> PaperSearchHistoryRead:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_search_history (
                    topic, source, result_count, query_text, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.topic,
                    payload.source,
                    payload.result_count,
                    payload.query_text,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM paper_search_history WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_search_history(row)

    def list_search_history(self) -> list[PaperSearchHistoryRead]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_search_history ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_search_history(row) for row in rows]
