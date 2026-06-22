from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.repositories.conversation_repo import ConversationRepository
from app.schemas.agent import AgentQueryResponse
from app.schemas.conversation import ConversationState, ConversationTurn


class ConversationContextService:
    _locks: dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, repo: ConversationRepository | None = None) -> None:
        self.repo = repo or ConversationRepository()

    @contextmanager
    def session_lock(self, session_id: str) -> Iterator[None]:
        lock = self._lock_for_session(session_id)
        with lock:
            yield

    def get_state(self, session_id: str) -> ConversationState | None:
        if not settings.conversation_context_enabled:
            return None
        return self.repo.get_state(session_id)

    def recent_turns(self, session_id: str, limit: int | None = None) -> list[ConversationTurn]:
        return self.repo.list_recent_turns(session_id, limit or settings.conversation_max_turns)

    def save_user_turn(self, *, session_id: str, message: str, message_id: str | None) -> None:
        if not settings.conversation_context_enabled:
            return
        self.repo.add_turn(
            session_id=session_id,
            role="user",
            content=message,
            message_id=message_id,
        )
        self.repo.prune_turns(session_id, settings.conversation_max_turns)

    def save_assistant_turn(
        self, *, session_id: str, content: str, message_id: str | None = None
    ) -> None:
        if not settings.conversation_context_enabled:
            return
        self.repo.add_turn(
            session_id=session_id,
            role="assistant",
            content=self._safe_summary(content),
            message_id=message_id,
        )
        self.repo.prune_turns(session_id, settings.conversation_max_turns)

    def clear_session(self, session_id: str) -> None:
        self.repo.clear_session(session_id)

    def update_from_agent_response(
        self,
        *,
        session_id: str,
        channel: str | None,
        chat_id: str | None,
        user_id: str | None,
        thread_id: str | None,
        user_message: str,
        assistant_text: str,
        response: AgentQueryResponse,
        previous_state: ConversationState | None = None,
    ) -> ConversationState | None:
        if not settings.conversation_context_enabled:
            return None

        if not response.success:
            self.save_assistant_turn(session_id=session_id, content=assistant_text)
            return previous_state

        tool_call = response.tool_calls[0] if response.tool_calls else None
        if tool_call is None or not tool_call.success:
            return previous_state

        last_tool = tool_call.tool_name
        last_arguments = self._state_arguments(last_tool, tool_call.arguments, previous_state)
        append_mode = bool(tool_call.arguments.get("append_mode"))
        last_result_refs = self._result_refs(
            last_tool,
            response.data,
            previous_state,
            append_mode=append_mode,
        )
        focused_paper_id = self._focused_paper_id(
            last_tool,
            tool_call.arguments,
            response.data,
            last_result_refs,
            previous_state,
        )

        state = self.repo.upsert_state(
            session_id=session_id,
            channel=channel,
            chat_id=chat_id,
            user_id=user_id,
            thread_id=thread_id,
            last_intent=response.intent,
            last_tool=last_tool,
            last_arguments=last_arguments,
            last_result_refs=last_result_refs,
            last_user_message=self._safe_summary(user_message),
            last_assistant_summary=self._safe_summary(assistant_text),
            last_focused_paper_id=focused_paper_id,
            expires_at=(
                datetime.now(UTC) + timedelta(hours=settings.conversation_ttl_hours)
            ).isoformat(),
        )
        self.save_assistant_turn(session_id=session_id, content=assistant_text)
        return state

    def session_hash(self, session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]

    def _state_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        previous_state: ConversationState | None,
    ) -> dict[str, Any]:
        if tool_name == "search_papers":
            return {
                "query": arguments.get("topic") or arguments.get("query"),
                "limit": int(arguments.get("max_results") or arguments.get("limit") or 5),
                "published_from": arguments.get("published_from"),
                "published_to": arguments.get("published_to"),
            }
        if previous_state is not None and tool_name in {
            "accept_paper",
            "ingest_paper",
            "get_paper_detail",
        }:
            state_args = dict(previous_state.last_arguments)
            state_args["last_action_paper_id"] = arguments.get("paper_id")
            return state_args
        if previous_state is not None and tool_name == "batch_ingest_papers":
            state_args = dict(previous_state.last_arguments)
            state_args["paper_ids"] = [int(value) for value in arguments.get("paper_ids") or []]
            state_args["source_positions"] = [
                int(value) for value in arguments.get("source_positions") or []
            ]
            return state_args
        return dict(arguments)

    def _result_refs(
        self,
        tool_name: str,
        data: Any,
        previous_state: ConversationState | None,
        *,
        append_mode: bool = False,
    ) -> list[dict[str, Any]]:
        if tool_name != "search_papers":
            return previous_state.last_result_refs if previous_state is not None else []
        refs: list[dict[str, Any]] = (
            list(previous_state.last_result_refs) if append_mode and previous_state else []
        )
        seen_ids = {item.get("paper_id") for item in refs if item.get("paper_id") is not None}
        seen_urls = {self._normalize_url(item.get("url")) for item in refs if item.get("url")}
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                paper_id = item.get("id")
                normalized_url = self._normalize_url(item.get("url"))
                if paper_id in seen_ids or (normalized_url and normalized_url in seen_urls):
                    continue
                if paper_id is not None:
                    seen_ids.add(paper_id)
                if normalized_url:
                    seen_urls.add(normalized_url)
                refs.append(
                    {
                        "position": len(refs) + 1,
                        "paper_id": item.get("id"),
                        "title": item.get("title"),
                        "url": item.get("url"),
                    }
                )
                if len(refs) >= settings.conversation_max_result_refs:
                    break
        return refs

    def _normalize_url(self, value: Any) -> str:
        return str(value or "").strip().lower().replace("http://", "https://").rstrip("/")

    def _focused_paper_id(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        data: Any,
        result_refs: list[dict[str, Any]],
        previous_state: ConversationState | None,
    ) -> int | None:
        if tool_name in {"accept_paper", "ingest_paper", "get_paper_detail"}:
            paper_id = arguments.get("paper_id")
            return int(paper_id) if paper_id is not None else None
        if tool_name == "batch_ingest_papers" and isinstance(data, dict):
            successful = [
                item
                for item in data.get("items") or []
                if isinstance(item, dict)
                and item.get("status") == "success"
                and item.get("paper_id") is not None
            ]
            if successful:
                return int(successful[-1]["paper_id"])
        if tool_name == "search_papers" and result_refs:
            first = result_refs[0].get("paper_id")
            return int(first) if first is not None else None
        return previous_state.last_focused_paper_id if previous_state is not None else None

    def _safe_summary(self, text: str, max_chars: int = 500) -> str:
        compact = " ".join(str(text or "").split())
        return compact[:max_chars]

    @classmethod
    def _lock_for_session(cls, session_id: str) -> threading.RLock:
        with cls._locks_guard:
            if session_id not in cls._locks:
                cls._locks[session_id] = threading.RLock()
            return cls._locks[session_id]
