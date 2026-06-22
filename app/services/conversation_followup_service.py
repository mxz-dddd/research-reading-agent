from __future__ import annotations

from datetime import date
import json
import re
from typing import Any

from app.core.llm_client import LLMClientError, OpenAICompatibleClient
from app.agent.tool_registry import TOOL_PARAMETER_SCHEMAS
from app.schemas.conversation import ConversationState, ConversationTurn, FollowupResolution
from app.services.paper_service import PaperService


CLEAR_PATTERNS = ("重新开始", "清除上下文", "忘掉刚才", "开始新任务")
BATCH_INGEST_HELP = (
    "我理解你想对刚才的论文做深入阅读，但没有找到可操作的论文编号。"
    "你可以说“对第2篇做深入阅读”或“对刚才5篇都做深入阅读”。"
)


class ConversationFollowupService:
    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client
        self.paper_service = PaperService()

    def resolve(
        self,
        message: str,
        state: ConversationState | None,
        *,
        recent_turns: list[ConversationTurn] | None = None,
    ) -> FollowupResolution:
        text = " ".join(str(message or "").split())
        if not text:
            return self._not_followup(text, "empty_message")

        if any(pattern in text for pattern in CLEAR_PATTERNS):
            return FollowupResolution(
                is_followup=True,
                resolved_message="已清除当前对话上下文，可以开始新的任务。",
                intent=None,
                tool_name=None,
                arguments={},
                confidence=1.0,
                reason="clear_context",
                clear_context=True,
            )

        if state is None:
            if self._is_batch_ingest_request(text):
                return self._direct_reply(BATCH_INGEST_HELP, "batch_ingest_context_miss")
            return self._not_followup(text, "context_miss")

        deterministic = self._resolve_with_rules(text, state)
        if deterministic is not None:
            return deterministic

        llm_resolution = self._resolve_with_llm(text, state, recent_turns or [])
        if llm_resolution is not None:
            return llm_resolution

        return self._not_followup(text, "no_rule_matched")

    def _resolve_with_rules(self, message: str, state: ConversationState) -> FollowupResolution | None:
        if self._is_batch_ingest_request(message):
            return self._resolve_batch_ingest(message, state)

        ordinal = self._extract_ordinal(message)
        if ordinal is not None:
            paper_id = self._paper_id_for_position(state, ordinal)
            if paper_id is None:
                return None
            tool = self._ordinal_tool(message)
            return FollowupResolution(
                is_followup=True,
                resolved_message=f"{tool} paper_id={paper_id}",
                intent=tool,
                tool_name=tool,
                arguments={"paper_id": paper_id},
                confidence=0.98,
                reason="result_ordinal_reference",
            )

        if self._has_search_context(state):
            time_range = self.paper_service._extract_published_range(message)
            has_time = any(time_range)
            quantity = self._extract_limit(message)
            topic = self._extract_new_topic(message)
            if has_time or quantity is not None or topic is not None or self._is_continue_search(message):
                args = dict(state.last_arguments)
                append_mode = self._is_append_search(message, topic=topic, has_time=has_time)
                desired_total = self._extract_total_limit(message)
                current_count = len(state.last_result_refs)
                if append_mode and desired_total is not None:
                    quantity = max(0, desired_total - current_count)
                    if quantity == 0:
                        if desired_total == current_count:
                            reply = (
                                f"当前已经有 {current_count} 篇结果，已满足你要求的一共 "
                                f"{desired_total} 篇。你可以说“再来5篇”或“接收第2篇”。"
                            )
                        else:
                            reply = (
                                f"当前已经有 {current_count} 篇结果，超过你要求的一共 "
                                f"{desired_total} 篇。我已保留现有结果；你可以重新搜索，"
                                "或指定要查看的论文范围。"
                            )
                        return self._direct_reply(reply, "desired_total_already_satisfied")
                if append_mode and quantity is None:
                    quantity = int(args.get("limit") or 5)
                if not args.get("query"):
                    return self._direct_reply(
                        "请先告诉我想搜索的研究主题，例如“搜索5篇VLF传播时延论文”。",
                        "search_topic_missing",
                    )
                if topic is not None:
                    args["query"] = topic
                if quantity is not None:
                    args["limit"] = quantity
                if has_time:
                    args["published_from"] = self._date_to_str(time_range[0])
                    args["published_to"] = self._date_to_str(time_range[1])
                exclude_urls = self._result_values(state, "url") if append_mode else []
                exclude_paper_ids = self._result_int_values(state, "paper_id") if append_mode else []
                exclude_arxiv_ids = [
                    arxiv_id
                    for url in exclude_urls
                    if (arxiv_id := self._arxiv_id_from_url(url)) is not None
                ]
                resolved = self._search_message(args)
                return FollowupResolution(
                    is_followup=True,
                    resolved_message=resolved,
                    intent="search_papers",
                    tool_name="search_papers",
                    arguments={
                        "topic": args.get("query"),
                        "max_results": int(args["limit"]) if args.get("limit") is not None else 5,
                        "published_from": args.get("published_from"),
                        "published_to": args.get("published_to"),
                        "exclude_urls": exclude_urls,
                        "exclude_paper_ids": exclude_paper_ids,
                        "exclude_arxiv_ids": exclude_arxiv_ids,
                        "append_mode": append_mode,
                        "result_offset": current_count if append_mode else 0,
                    },
                    confidence=0.95,
                    reason="append_search" if append_mode else "search_state_merge",
                    append_mode=append_mode,
                    exclude_previous_results=append_mode,
                    requested_additional_limit=quantity if append_mode else None,
                    desired_total_limit=desired_total,
                )

        if self._has_pronoun_reference(message) and state.last_focused_paper_id is not None:
            tool = self._pronoun_tool(message)
            if tool is not None:
                return FollowupResolution(
                    is_followup=True,
                    resolved_message=f"{tool} paper_id={state.last_focused_paper_id}",
                    intent=tool,
                    tool_name=tool,
                    arguments={"paper_id": state.last_focused_paper_id},
                    confidence=0.9,
                    reason="focused_paper_reference",
                )

        return None

    def _resolve_with_llm(
        self,
        message: str,
        state: ConversationState,
        recent_turns: list[ConversationTurn],
    ) -> FollowupResolution | None:
        client = self.llm_client or OpenAICompatibleClient()
        if hasattr(client, "is_configured") and not client.is_configured():
            return None
        try:
            payload = {
                "last_intent": state.last_intent,
                "last_tool": state.last_tool,
                "last_arguments": state.last_arguments,
                "last_result_refs": [
                    {
                        "position": item.get("position"),
                        "paper_id": item.get("paper_id"),
                        "title": item.get("title"),
                    }
                    for item in state.last_result_refs[:10]
                ],
                "recent_turns": [
                    {"role": turn.role, "content": turn.content[:200]}
                    for turn in recent_turns[-6:]
                ],
                "message": message,
            }
            text = client.responses_text(
                json.dumps(payload, ensure_ascii=False),
                instructions=(
                    "Resolve whether the current message is a follow-up. "
                    "Inherit omitted details from context. Do not invent paper_id; "
                    "第N篇 must be resolved from result refs. If current message is a new task, "
                    "return is_followup false. Return strict JSON only with keys: "
                    "is_followup, intent, tool_name, arguments, confidence."
                ),
                temperature=0.0,
            )
            parsed = json.loads(text)
            if not parsed.get("is_followup"):
                return None
            tool_name = self._normalize_llm_tool(parsed.get("tool_name"))
            if tool_name == "batch_ingest_papers":
                return self._resolve_batch_ingest(message, state)
            if tool_name not in TOOL_PARAMETER_SCHEMAS:
                return self._direct_reply(BATCH_INGEST_HELP, "unknown_llm_tool")
            arguments = parsed.get("arguments") or {}
            if tool_name == "ingest_paper" and not arguments.get("paper_id"):
                if state.last_focused_paper_id is None:
                    return self._direct_reply(BATCH_INGEST_HELP, "single_ingest_reference_missing")
                arguments = {"paper_id": state.last_focused_paper_id}
            return FollowupResolution(
                is_followup=True,
                resolved_message=message,
                intent=parsed.get("intent"),
                tool_name=tool_name,
                arguments=arguments,
                confidence=float(parsed.get("confidence") or 0.5),
                reason="llm_context_merge",
            )
        except (LLMClientError, json.JSONDecodeError, TypeError, ValueError, KeyError):
            return None

    def _extract_limit(self, message: str) -> int | None:
        match = re.search(r"(?:只要|再搜|再来|再给我|再补充|补充|换成|给我|多给我)?\s*(\d+)\s*篇", message)
        if match:
            return max(1, min(20, int(match.group(1))))
        if "多给我几篇" in message:
            return 10
        return None

    def _is_batch_ingest_request(self, message: str) -> bool:
        has_read_intent = any(
            phrase in message
            for phrase in ("深入阅读", "深度阅读", "精读", "读一遍", "进行阅读")
        )
        has_batch_reference = any(
            phrase in message
            for phrase in ("全部", "都", "这几篇", "这些", "这五篇", "这5篇", "刚才")
        ) or bool(re.search(r"前\s*[一二两三四五六七八九十\d]+\s*篇", message)) \
            or bool(re.search(r"第\s*[一二两三四五六七八九十\d]+\s*(?:到|至|-|~)", message))
        return has_read_intent and has_batch_reference

    def _resolve_batch_ingest(
        self,
        message: str,
        state: ConversationState,
    ) -> FollowupResolution:
        if not state.last_result_refs:
            return self._direct_reply(BATCH_INGEST_HELP, "batch_ingest_no_results")

        positions, explicit_range = self._batch_positions(message, state)
        if not explicit_range and len(state.last_result_refs) > 10:
            return self._direct_reply(
                f"当前列表有 {len(state.last_result_refs)} 篇，一次最多深入阅读 10 篇。"
                "请说“对前10篇深入阅读”或指定范围。",
                "batch_ingest_limit_exceeded",
            )
        if not positions or len(positions) > 10:
            return self._direct_reply(BATCH_INGEST_HELP, "batch_ingest_invalid_range")

        refs_by_position = {
            int(item.get("position")): item
            for item in state.last_result_refs
            if item.get("position") is not None and item.get("paper_id") is not None
        }
        selected = [refs_by_position[position] for position in positions if position in refs_by_position]
        if len(selected) != len(positions):
            return self._direct_reply(BATCH_INGEST_HELP, "batch_ingest_position_missing")
        return FollowupResolution(
            is_followup=True,
            resolved_message=message,
            intent="batch_ingest_papers",
            tool_name="batch_ingest_papers",
            arguments={
                "paper_ids": [int(item["paper_id"]) for item in selected],
                "source_positions": positions,
            },
            confidence=0.99,
            reason="batch_result_reference",
        )

    def _batch_positions(
        self,
        message: str,
        state: ConversationState,
    ) -> tuple[list[int], bool]:
        number = r"[一二两三四五六七八九十\d]+"
        range_match = re.search(rf"第?\s*({number})\s*(?:到|至|-|~)\s*第?\s*({number})\s*篇", message)
        if range_match:
            start = self._parse_number(range_match.group(1))
            end = self._parse_number(range_match.group(2))
            if start is None or end is None or start > end:
                return [], True
            return list(range(start, end + 1)), True

        front_match = re.search(rf"前\s*({number})\s*篇", message)
        if front_match:
            count = self._parse_number(front_match.group(1)) or 0
            return list(range(1, count + 1)), True

        count_match = re.search(rf"(?:这|刚才(?:的)?)\s*({number})\s*篇", message)
        if count_match:
            count = self._parse_number(count_match.group(1)) or 0
            return [int(item["position"]) for item in state.last_result_refs[:count]], True

        return [int(item["position"]) for item in state.last_result_refs], False

    def _parse_number(self, value: str) -> int | None:
        if value.isdigit():
            return int(value)
        values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        if value in values:
            return values[value]
        if value.startswith("十") and len(value) == 2:
            return 10 + values.get(value[1], 0)
        if value.endswith("十") and len(value) == 2:
            return values.get(value[0], 0) * 10
        return None

    def _normalize_llm_tool(self, tool_name: Any) -> str:
        name = str(tool_name or "")
        return {"read_paper": "ingest_paper", "read_papers": "batch_ingest_papers"}.get(name, name)

    def _direct_reply(self, text: str, reason: str) -> FollowupResolution:
        return FollowupResolution(
            is_followup=True,
            resolved_message=text,
            intent=None,
            tool_name=None,
            arguments={},
            confidence=1.0,
            reason=reason,
            direct_reply=True,
        )

    def _extract_total_limit(self, message: str) -> int | None:
        match = re.search(r"(?:一共(?:要)?|总共(?:要)?|合计(?:要)?)\s*(\d+)\s*篇", message)
        return max(1, min(20, int(match.group(1)))) if match else None

    def _extract_new_topic(self, message: str) -> str | None:
        if not re.search(r"(换成|改搜|再查一下)", message):
            return None
        topic = re.sub(r"(?:近|最近)\s*[一二两三四五六七八九十\d]+\s*年", " ", message)
        topic = re.sub(r"(?:19|20)\d{2}\s*年?\s*以来", " ", topic)
        topic = re.sub(r"(?:19|20)\d{2}\s*年?\s*(?:到|至|-|~)\s*(?:19|20)\d{2}\s*年?", " ", topic)
        topic = re.sub(r"(换成|改搜|再查一下|相关的|相关|论文|的|只看|只要|要)", " ", topic)
        topic = re.sub(r"[，,。.!！?？]", " ", topic)
        topic = " ".join(topic.split())
        return topic or None

    def _extract_ordinal(self, message: str) -> int | None:
        match = re.search(r"第\s*(\d+)\s*篇", message)
        if match:
            return int(match.group(1))
        return None

    def _ordinal_tool(self, message: str) -> str:
        if any(word in message for word in ("接收", "保存")):
            return "accept_paper"
        if any(word in message for word in ("深入阅读", "精读", "归档")):
            return "ingest_paper"
        return "get_paper_detail"

    def _pronoun_tool(self, message: str) -> str | None:
        if any(word in message for word in ("接收", "保存")):
            return "accept_paper"
        if any(word in message for word in ("深入阅读", "精读", "总结")):
            return "ingest_paper"
        if any(word in message for word in ("看看", "详情")):
            return "get_paper_detail"
        return None

    def _has_pronoun_reference(self, message: str) -> bool:
        return any(word in message for word in ("它", "这篇", "刚才那篇"))

    def _paper_id_for_position(self, state: ConversationState, position: int) -> int | None:
        for item in state.last_result_refs:
            if int(item.get("position") or -1) == position and item.get("paper_id") is not None:
                return int(item["paper_id"])
        return None

    def _is_continue_search(self, message: str) -> bool:
        return any(word in message for word in ("继续", "还有吗", "换一批", "再来", "再给", "补充", "一共"))

    def _is_append_search(self, message: str, *, topic: str | None, has_time: bool) -> bool:
        if topic is not None or has_time:
            return False
        if any(word in message for word in ("重新搜索", "重新搜", "重新开始后新搜索", "换个主题")):
            return False
        return any(word in message for word in ("继续", "还有吗", "换一批", "再来", "再给", "再补充", "补充", "一共"))

    def _has_search_context(self, state: ConversationState) -> bool:
        return state.last_tool == "search_papers" or bool(state.last_arguments.get("query"))

    def _result_values(self, state: ConversationState, key: str) -> list[str]:
        return [str(item[key]) for item in state.last_result_refs if item.get(key)]

    def _result_int_values(self, state: ConversationState, key: str) -> list[int]:
        return [int(item[key]) for item in state.last_result_refs if item.get(key) is not None]

    def _arxiv_id_from_url(self, url: str) -> str | None:
        match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", url, flags=re.IGNORECASE)
        return match.group(1).removesuffix(".pdf").lower() if match else None

    def _search_message(self, args: dict[str, Any]) -> str:
        query = args.get("query") or ""
        limit = int(args.get("limit") or 5)
        return f"搜索 {limit} 篇 {query} 论文"

    def _date_to_str(self, value: date | None) -> str | None:
        return value.isoformat() if value else None

    def _not_followup(self, message: str, reason: str) -> FollowupResolution:
        return FollowupResolution(
            is_followup=False,
            resolved_message=message,
            intent=None,
            tool_name=None,
            arguments={},
            confidence=0.0,
            reason=reason,
        )
