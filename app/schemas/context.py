from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ContextItem(BaseModel):
    item_type: str
    source_type: str
    source_id: str | None = None
    content: str
    score: float | None = None
    reason: str | None = None
    metadata: dict[str, Any] = {}


class ContextPackRead(BaseModel):
    context_pack_id: str
    user_id: str
    session_id: str
    query: str
    mode: str
    paper_id: str | None = None
    token_budget: int
    estimated_tokens: int
    item_count: int
    items: list[ContextItem]
    created_at: str | None = None
