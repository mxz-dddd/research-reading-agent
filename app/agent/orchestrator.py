from __future__ import annotations

from app.core.exceptions import AppError

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from app.agent.answer_builder import build_final_answer
from app.agent.argument_resolver import resolve_arguments
from app.agent.fallback_router import route_with_fallback
from app.agent.prompts import AGENT_ROUTER_PROMPT
from app.agent.tool_registry import ToolRegistry
from app.core.config import settings
from app.repositories.session_repo import SessionStateRepository
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse, AgentToolCall


class AgentOrchestrator:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.session_repo = SessionStateRepository()

    def query(self, payload: AgentQueryRequest) -> AgentQueryResponse:
        message = payload.text
        route = self._route_with_llm(message)
        routing_method = "llm"
        if route is None:
            route = self._route_with_fallback(message)
            routing_method = "fallback"

        tool_name = route["tool_name"]
        arguments = dict(route.get("arguments", {}))
        intent = route.get("intent") or tool_name

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
            final_answer = build_final_answer(tool_name, data)
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
        except (AppError, ValueError) as exc:
            error = exc.detail if isinstance(exc, AppError) else str(exc)
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
                final_answer=f"我没能完成这个操作：{error}",
                data=None,
                error=error,
                routing_method=routing_method,
                answer=f"我没能完成这个操作：{error}",
                used_tool=tool_name,
            )

    def _route_with_llm(self, message: str) -> dict[str, Any] | None:
        if not settings.openai_api_key:
            return None

        body = {
            "model": settings.openai_model,
            "input": [
                {"role": "system", "content": AGENT_ROUTER_PROMPT},
                {"role": "user", "content": message},
            ],
            "tools": self._openai_tools(),
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=45, context=self._ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
            return self._extract_function_call(data)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

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
        return [
            self._tool_schema("search_papers", {"topic": "string", "max_results": "integer"}),
            self._tool_schema("accept_paper", {"paper_id": "integer", "ordinal": "integer"}),
            self._tool_schema("ingest_paper", {"paper_id": "integer", "ordinal": "integer"}),
            self._tool_schema("list_accepted_papers", {}),
            self._tool_schema("get_paper_detail", {"paper_id": "integer", "ordinal": "integer"}),
            self._tool_schema("generate_knowledge", {"topic": "string"}),
            self._tool_schema("generate_innovation", {"topic": "string"}),
            self._tool_schema(
                "run_research_workflow",
                {
                    "topic": "string",
                    "max_results": "integer",
                    "accept_top_k": "integer",
                    "dry_run": "boolean",
                    "index_rag": "boolean",
                    "rag_chunk_size": "integer",
                    "rag_chunk_overlap": "integer",
                },
            ),
            self._tool_schema("get_latest_workflow", {}),
            self._tool_schema("list_workflow_history", {"limit": "integer"}),
            self._tool_schema("get_workflow_detail", {"run_id": "string"}),
            self._tool_schema("generate_workflow_report", {"run_id": "string"}),
            self._tool_schema("get_workflow_report", {"run_id": "string"}),
            self._tool_schema("index_paper_rag", {"paper_id": "integer", "ordinal": "integer"}),
            self._tool_schema("rag_search", {"query": "string", "top_k": "integer", "paper_id": "integer", "ordinal": "integer", "retrieval_mode": "string"}),
            self._tool_schema("rag_answer", {"query": "string", "top_k": "integer", "paper_id": "integer", "ordinal": "integer", "retrieval_mode": "string"}),
            self._tool_schema("get_latest_rag_traces", {"limit": "integer"}),
            self._tool_schema("get_rag_trace_detail", {"trace_id": "string"}),
            self._tool_schema("get_rag_traces_by_paper", {"paper_id": "integer", "ordinal": "integer", "limit": "integer"}),
            self._tool_schema("add_rag_trace_feedback", {"trace_id": "string", "relevance_label": "string", "expected_terms": "array", "notes": "string"}),
            self._tool_schema("get_rag_evaluation_summary", {}),
            self._tool_schema("get_rag_trace_evaluation_detail", {"trace_id": "string"}),
            self._tool_schema("add_rag_evidence_feedback", {"trace_id": "string", "chunk_id": "string", "rank": "integer", "relevance_score": "integer", "notes": "string"}),
            self._tool_schema("get_rag_evidence_evaluation_summary", {"trace_id": "string"}),
            self._tool_schema("get_rag_trace_evidence_evaluation", {"trace_id": "string"}),
            self._tool_schema("help", {}),
        ]

    def _tool_schema(self, name: str, properties: dict[str, str]) -> dict[str, Any]:
        return {
            "type": "function",
            "name": name,
            "description": f"调用 {name} 工具",
            "parameters": {
                "type": "object",
                "properties": {
                    key: {"type": value}
                    for key, value in properties.items()
                },
                "additionalProperties": False,
            },
        }

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())
