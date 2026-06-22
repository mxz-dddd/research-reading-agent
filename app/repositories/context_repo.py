import json
from datetime import UTC, datetime
from sqlite3 import Row
from uuid import uuid4

from app.core.database import get_connection
from app.schemas.context import ContextItem, ContextPackRead


def _now() -> str:
    return datetime.now(UTC).isoformat()


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _row_to_context_pack(row: Row) -> ContextPackRead:
    data = dict(row)
    context = json.loads(data.pop("context_json") or "{}")
    items = [ContextItem(**item) for item in context.get("items", [])]
    return ContextPackRead(
        context_pack_id=data["context_pack_id"],
        user_id=data["user_id"],
        session_id=data["session_id"],
        query=data["query"],
        mode=data["mode"],
        paper_id=data["paper_id"],
        token_budget=data["token_budget"],
        estimated_tokens=data["estimated_tokens"],
        item_count=data["item_count"],
        items=items,
        created_at=data["created_at"],
    )


class ContextPackRepository:
    def create_context_pack(
        self,
        *,
        user_id: str,
        session_id: str,
        query: str,
        mode: str,
        items: list[ContextItem],
        paper_id: str | None = None,
        token_budget: int = 6000,
        context_pack_id: str | None = None,
    ) -> ContextPackRead:
        now = _now()
        pack_id = context_pack_id or f"ctx_{uuid4().hex[:12]}"
        context = {"items": [item.model_dump() for item in items]}
        serialized = json.dumps(context, ensure_ascii=False)
        estimated = estimate_tokens(query + "\n" + "\n".join(item.content for item in items))
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO context_packs (
                    context_pack_id, user_id, session_id, query, mode, paper_id,
                    token_budget, estimated_tokens, item_count, context_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack_id,
                    user_id,
                    session_id,
                    query,
                    mode,
                    paper_id,
                    token_budget,
                    estimated,
                    len(items),
                    serialized,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM context_packs WHERE context_pack_id = ?",
                (pack_id,),
            ).fetchone()
        return _row_to_context_pack(row)

    def get_context_pack(self, context_pack_id: str) -> ContextPackRead | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM context_packs WHERE context_pack_id = ?",
                (context_pack_id,),
            ).fetchone()
        return _row_to_context_pack(row) if row else None

    def list_latest(
        self,
        user_id: str = "default",
        session_id: str = "default",
        limit: int = 10,
    ) -> list[ContextPackRead]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM context_packs
                WHERE user_id = ? AND session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, session_id, max(1, min(limit, 50))),
            ).fetchall()
        return [_row_to_context_pack(row) for row in rows]
