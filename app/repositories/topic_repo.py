from datetime import datetime, timezone
from sqlite3 import Row

from app.core.database import get_connection
from app.schemas.topic import TopicCreate, TopicRead


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_topic(row: Row) -> TopicRead:
    return TopicRead(**dict(row))


class TopicRepository:
    def create(self, payload: TopicCreate) -> TopicRead:
        now = _now()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO research_topics (title, description, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (payload.title, payload.description, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM research_topics WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_topic(row)

    def list(self) -> list[TopicRead]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM research_topics ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_topic(row) for row in rows]
