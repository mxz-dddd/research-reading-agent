from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConversationTurn:
    id: int | None
    session_id: str
    role: str
    content: str
    message_id: str | None
    created_at: str


@dataclass(frozen=True)
class ConversationState:
    session_id: str
    channel: str | None
    chat_id: str | None
    user_id: str | None
    thread_id: str | None
    last_intent: str | None
    last_tool: str | None
    last_arguments: dict[str, Any]
    last_result_refs: list[dict[str, Any]]
    last_user_message: str | None
    last_assistant_summary: str | None
    last_focused_paper_id: int | None
    updated_at: str
    expires_at: str


@dataclass(frozen=True)
class FollowupResolution:
    is_followup: bool
    resolved_message: str
    intent: str | None
    tool_name: str | None
    arguments: dict[str, Any]
    confidence: float
    reason: str
    clear_context: bool = False
    append_mode: bool = False
    exclude_previous_results: bool = False
    requested_additional_limit: int | None = None
    desired_total_limit: int | None = None
    direct_reply: bool = False
