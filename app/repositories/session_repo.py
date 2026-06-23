import json
from datetime import UTC, datetime
from typing import Any

from app.core.database import get_connection


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStateRepository:
    def get_state(self, user_id: str, session_id: str) -> dict[str, Any]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT state_json FROM session_state WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
        if row is None:
            return {}
        return json.loads(row["state_json"])

    def save_state(self, user_id: str, session_id: str, state: dict[str, Any]) -> None:
        now = _now()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO session_state (user_id, session_id, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, session_id)
                DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
                """,
                (user_id, session_id, json.dumps(state, ensure_ascii=False), now),
            )
            conn.commit()

    def save_recent_search_results(
        self,
        user_id: str,
        session_id: str,
        papers: list[dict[str, Any]],
    ) -> None:
        state = self.get_state(user_id, session_id)
        state["recent_search_results"] = [
            {
                "position": index,
                "paper_id": paper.get("id"),
                "title": paper.get("title"),
            }
            for index, paper in enumerate(papers, start=1)
        ]
        self.save_state(user_id, session_id, state)

    def resolve_recent_position(
        self,
        user_id: str,
        session_id: str,
        position: int,
    ) -> int | None:
        state = self.get_state(user_id, session_id)
        for item in state.get("recent_search_results", []):
            if item.get("position") == position:
                return item.get("paper_id")
        return None
