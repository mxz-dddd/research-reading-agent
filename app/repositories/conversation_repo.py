import json
from datetime import UTC, datetime
from sqlite3 import Row
from typing import Any

from app.core.database import get_connection, init_db
from app.schemas.conversation import ConversationState, ConversationTurn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_state(row: Row) -> ConversationState:
    return ConversationState(
        session_id=row["session_id"],
        channel=row["channel"],
        chat_id=row["chat_id"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        last_intent=row["last_intent"],
        last_tool=row["last_tool"],
        last_arguments=json.loads(row["last_arguments_json"] or "{}"),
        last_result_refs=json.loads(row["last_result_refs_json"] or "[]"),
        last_user_message=row["last_user_message"],
        last_assistant_summary=row["last_assistant_summary"],
        last_focused_paper_id=row["last_focused_paper_id"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
    )


def _row_to_turn(row: Row) -> ConversationTurn:
    return ConversationTurn(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        message_id=row["message_id"],
        created_at=row["created_at"],
    )


class ConversationRepository:
    def __init__(self) -> None:
        init_db()

    def add_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        message_id: str | None,
    ) -> ConversationTurn | None:
        now = _now()
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO conversation_turns (
                    session_id, role, content, message_id, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, message_id, now),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM conversation_turns WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_turn(row)

    def list_recent_turns(self, session_id: str, limit: int) -> list[ConversationTurn]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversation_turns
                WHERE session_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [_row_to_turn(row) for row in reversed(rows)]

    def prune_turns(self, session_id: str, keep: int) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM conversation_turns
                WHERE session_id = ?
                  AND id NOT IN (
                    SELECT id FROM conversation_turns
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                  )
                """,
                (session_id, session_id, keep),
            )
            conn.commit()

    def get_state(self, session_id: str, *, now_iso: str | None = None) -> ConversationState | None:
        now_iso = now_iso or _now()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM conversation_task_state
                WHERE session_id = ? AND expires_at > ?
                """,
                (session_id, now_iso),
            ).fetchone()
        if row is None:
            return None
        return _row_to_state(row)

    def upsert_state(
        self,
        *,
        session_id: str,
        channel: str | None,
        chat_id: str | None,
        user_id: str | None,
        thread_id: str | None,
        last_intent: str | None,
        last_tool: str | None,
        last_arguments: dict[str, Any],
        last_result_refs: list[dict[str, Any]],
        last_user_message: str | None,
        last_assistant_summary: str | None,
        last_focused_paper_id: int | None,
        expires_at: str,
    ) -> ConversationState:
        now = _now()
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO conversation_task_state (
                    session_id, channel, chat_id, user_id, thread_id,
                    last_intent, last_tool, last_arguments_json, last_result_refs_json,
                    last_user_message, last_assistant_summary, last_focused_paper_id,
                    updated_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    channel=excluded.channel,
                    chat_id=excluded.chat_id,
                    user_id=excluded.user_id,
                    thread_id=excluded.thread_id,
                    last_intent=excluded.last_intent,
                    last_tool=excluded.last_tool,
                    last_arguments_json=excluded.last_arguments_json,
                    last_result_refs_json=excluded.last_result_refs_json,
                    last_user_message=excluded.last_user_message,
                    last_assistant_summary=excluded.last_assistant_summary,
                    last_focused_paper_id=excluded.last_focused_paper_id,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at
                """,
                (
                    session_id,
                    channel,
                    chat_id,
                    user_id,
                    thread_id,
                    last_intent,
                    last_tool,
                    json.dumps(last_arguments, ensure_ascii=False),
                    json.dumps(last_result_refs, ensure_ascii=False),
                    last_user_message,
                    last_assistant_summary,
                    last_focused_paper_id,
                    now,
                    expires_at,
                ),
            )
            conn.commit()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversation_task_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("conversation state was not persisted")
        return _row_to_state(row)

    def clear_session(self, session_id: str) -> None:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM conversation_turns WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM conversation_task_state WHERE session_id = ?", (session_id,))
            conn.commit()
