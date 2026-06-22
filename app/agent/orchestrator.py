import json
import logging
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from fastapi import HTTPException

from app.agent.answer_builder import build_final_answer
from app.agent.argument_resolver import resolve_arguments
from app.agent.fallback_router import route_with_fallback
from app.agent.multi_step import MultiStepOrchestrator
from app.agent.prompts import AGENT_ROUTER_PROMPT
from app.agent.tool_registry import ToolRegistry
from app.core.config import settings
from app.core.llm_client import LLMClientError, OpenAICompatibleClient
from app.repositories.session_repo import SessionStateRepository
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse, AgentToolCall

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.session_repo = SessionStateRepository()

    def query(self, payload: AgentQueryRequest) -> AgentQueryResponse:
        message = payload.text
        if getattr(settings, "agent_multi_step_enabled", False):
            response = MultiStepOrchestrator(
                registry=self.registry,
                session_repo=self.session_repo,
            ).run(payload, tool_schemas=self._openai_tools())
            if response is not None:
                return response
        route = self._route_with_llm(message)
        routing_method = "llm"
        if route is None:
            route = self._route_with_fallback(message)
            routing_method = "fallback"

        return self._execute_route(payload=payload, route=route, routing_method=routing_method)

    def query_with_route(
        self,
        payload: AgentQueryRequest,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        intent: str | None = None,
        routing_method: str = "context",
    ) -> AgentQueryResponse:
        return self._execute_route(
            payload=payload,
            route={"intent": intent or tool_name, "tool_name": tool_name, "arguments": arguments},
            routing_method=routing_method,
        )

    def _execute_route(
        self,
        *,
        payload: AgentQueryRequest,
        route: dict[str, Any],
        routing_method: str,
    ) -> AgentQueryResponse:
        tool_name = self._normalize_tool_name(route["tool_name"])
        arguments = dict(route.get("arguments", {}))
        intent = tool_name if route.get("intent") in {"read_paper", "read_papers"} else route.get("intent") or tool_name

        try:
            arguments = self._resolve_arguments(
                arguments=arguments,
                payload=payload,
                tool_name=tool_name,
            )
            data = self.registry.call(tool_name, **arguments)
            tool_calls = [
                AgentToolCall(
                    tool_name=tool_name,
                    arguments=arguments,
                    success=True,
                )
            ]
            final_answer = build_final_answer(tool_name, data, arguments=arguments)
            return AgentQueryResponse(
                success=True,
                intent=intent,
                chosen_tool=tool_name,
                tool_calls=tool_calls,
                final_answer=final_answer,
                data=data,
                error=None,
                routing_method=routing_method,
                answer=final_answer,
                used_tool=tool_name,
            )
        except (HTTPException, ValueError) as exc:
            error = exc.detail if isinstance(exc, HTTPException) else str(exc)
            user_error = (
                "我理解你想对刚才的论文做深入阅读，但没有找到可操作的论文编号。"
                "你可以说“对第2篇做深入阅读”或“对刚才5篇都做深入阅读”。"
                if "未知工具" in error
                else error
            )
            return AgentQueryResponse(
                success=False,
                intent=intent,
                chosen_tool=tool_name,
                tool_calls=[
                    AgentToolCall(
                        tool_name=tool_name,
                        arguments=arguments,
                        success=False,
                        error=error,
                    )
                ],
                final_answer=f"我没能完成这个操作：{user_error}",
                data=None,
                error=error,
                routing_method=routing_method,
                answer=f"我没能完成这个操作：{user_error}",
                used_tool=tool_name,
            )

    def _route_with_llm(self, message: str) -> dict[str, Any] | None:
        client = OpenAICompatibleClient()
        if not client.is_configured():
            return None

        try:
            data = client.responses(
                message,
                instructions=AGENT_ROUTER_PROMPT,
                tools=self._openai_tools(),
            )
            return self._extract_function_call(data)
        except (LLMClientError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "LLM routing failed, falling back to rule-based router (model=%s): %s",
                client.model,
                exc,
            )
            return None

    def _normalize_tool_name(self, tool_name: Any) -> str:
        name = str(tool_name or "")
        return {"read_paper": "ingest_paper", "read_papers": "batch_ingest_papers"}.get(name, name)

    def _extract_function_call(self, data: dict[str, Any]) -> dict[str, Any] | None:
        for item in data.get("output", []):
            if item.get("type") in {"function_call", "tool_call"}:
                name = item.get("name")
                raw_args = item.get("arguments") or "{}"
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if name:
                    return {"intent": name, "tool_name": name, "arguments": args}
            for content in item.get("content", []):
                if content.get("type") in {"function_call", "tool_call"}:
                    name = content.get("name")
                    raw_args = content.get("arguments") or "{}"
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    if name:
                        return {"intent": name, "tool_name": name, "arguments": args}
        return None

    def _route_with_fallback(self, message: str) -> dict[str, Any]:
        return route_with_fallback(message)

    def _resolve_arguments(
        self,
        *,
        arguments: dict[str, Any],
        payload: AgentQueryRequest,
        tool_name: str,
    ) -> dict[str, Any]:
        return resolve_arguments(
            arguments=arguments,
            payload=payload,
            tool_name=tool_name,
            session_repo=self.session_repo,
        )

    def _openai_tools(self) -> list[dict[str, Any]]:
        # 单一事实源：直接由 ToolRegistry 派生，避免与已注册工具集漂移。
        return self.registry.openai_tool_schemas()

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())

