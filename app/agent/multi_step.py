"""多步 plan-execute Agent 循环（opt-in）。

通过 AGENT_MULTI_STEP_ENABLED=true 开启。每一步由 LLM 决定调用哪个工具，
工具结果回填到对话中，直到 LLM 给出最终文本回答或达到 AGENT_MAX_STEPS。
任何 LLM 异常都会让调用方降级回原有"单轮路由"流程，不影响现有行为。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from app.agent.answer_builder import build_final_answer
from app.agent.argument_resolver import resolve_arguments
from app.core.config import settings
from app.core.llm_client import LLMClientError, OpenAICompatibleClient
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse, AgentToolCall

MULTI_STEP_SYSTEM_PROMPT = """你是科研论文阅读工作台的智能体。你可以多步调用工具完成用户请求：
1. 每一步选择最合适的工具；可以串联多个工具（例如先搜索论文，再接收、ingest、建立索引）。
2. 工具结果会以 tool 消息返回给你，请根据结果决定下一步。
3. 完成后用中文输出最终总结，说明做了什么、关键结果和建议的下一步。
4. 不要编造工具结果中不存在的信息。
5. 如果无法完成，明确说明原因。"""

_MAX_TOOL_RESULT_CHARS = 4000
_MAX_STEPS_LIMIT = 8
_WRITE_TOOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "accept_paper": ("接收", "接受", "accept"),
    "ingest_paper": ("入库", "下载", "ingest"),
    "batch_ingest_papers": ("全部深入阅读", "批量深入阅读", "都进行深入阅读"),
    "generate_knowledge": ("生成知识", "知识树", "generate knowledge"),
    "generate_innovation": ("生成创新", "创新点", "generate innovation"),
    "run_research_workflow": ("运行工作流", "执行工作流", "run workflow"),
    "generate_workflow_report": ("生成报告", "generate report"),
    "index_paper_rag": ("建立索引", "构建索引", "index"),
    "add_rag_trace_feedback": ("添加反馈", "标注", "feedback"),
    "add_rag_evidence_feedback": ("证据反馈", "证据标注", "feedback"),
}


def _to_chat_tools(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Responses API style tool definitions to the legacy helper shape."""
    chat_tools = []
    for schema in tool_schemas:
        chat_tools.append(
            {
                "type": "function",
                "function": {
                    "name": schema.get("name"),
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {"type": "object", "properties": {}}),
                },
            }
        )
    return chat_tools


def _serialize_tool_result(data: Any) -> str:
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    try:
        text = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(data)
    if len(text) > _MAX_TOOL_RESULT_CHARS:
        text = text[:_MAX_TOOL_RESULT_CHARS] + "...(truncated)"
    return text


class MultiStepOrchestrator:
    def __init__(
        self,
        *,
        registry: Any,
        session_repo: Any,
        client: OpenAICompatibleClient | None = None,
        max_steps: int | None = None,
    ) -> None:
        self.registry = registry
        self.session_repo = session_repo
        self.client = client or OpenAICompatibleClient()
        configured_steps = (
            max_steps if max_steps is not None else getattr(settings, "agent_max_steps", 3)
        )
        self.max_steps = max(1, min(int(configured_steps), _MAX_STEPS_LIMIT))

    def run(
        self,
        payload: AgentQueryRequest,
        tool_schemas: list[dict[str, Any]],
    ) -> AgentQueryResponse | None:
        """执行多步循环；返回 None 表示交回单轮路由 fallback。"""
        if not self.client.is_configured():
            return None

        chat_tools = _to_chat_tools(tool_schemas)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": MULTI_STEP_SYSTEM_PROMPT},
            {"role": "user", "content": payload.text},
        ]
        executed: list[AgentToolCall] = []
        executed_write_tools: set[str] = set()
        last_tool_name: str | None = None
        last_data: Any = None

        for _step in range(self.max_steps):
            try:
                response = self.client.chat(messages, tools=chat_tools)
            except LLMClientError:
                if not executed:
                    return None
                return self._summary_response(payload, executed, last_tool_name, last_data)

            tool_calls = self.client.extract_tool_calls(response)
            if not tool_calls:
                text = self.client.extract_text(response)
                if text:
                    return self._final_response(text, executed, last_tool_name, last_data)
                if executed:
                    return self._summary_response(payload, executed, last_tool_name, last_data)
                return None

            assistant_message = self._assistant_message(response)
            if assistant_message is not None:
                messages.append(assistant_message)

            for call in tool_calls:
                tool_name = call["name"]
                arguments = dict(call.get("arguments") or {})
                try:
                    self._guard_tool_call(
                        tool_name=tool_name,
                        user_text=payload.text,
                        executed_write_tools=executed_write_tools,
                    )
                    arguments = resolve_arguments(
                        arguments=arguments,
                        payload=payload,
                        tool_name=tool_name,
                        session_repo=self.session_repo,
                    )
                    data = self.registry.call(tool_name, **arguments)
                    if tool_name in _WRITE_TOOL_KEYWORDS:
                        executed_write_tools.add(tool_name)
                    executed.append(
                        AgentToolCall(tool_name=tool_name, arguments=arguments, success=True)
                    )
                    last_tool_name = tool_name
                    last_data = data
                    result_text = _serialize_tool_result(data)
                except (HTTPException, ValueError, KeyError) as exc:
                    error = exc.detail if isinstance(exc, HTTPException) else str(exc)
                    executed.append(
                        AgentToolCall(
                            tool_name=tool_name,
                            arguments=arguments,
                            success=False,
                            error=str(error),
                        )
                    )
                    result_text = json.dumps(
                        {"success": False, "error": str(error)}, ensure_ascii=False
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or tool_name,
                        "content": result_text,
                    }
                )

        # 步数耗尽：请求一次纯文本总结，失败则使用模板总结。
        try:
            final_text = self.client.chat_text(
                messages
                + [
                    {
                        "role": "user",
                        "content": "请根据以上工具结果，用中文给出最终总结，不要再调用工具。",
                    }
                ]
            )
            return self._final_response(final_text, executed, last_tool_name, last_data)
        except LLMClientError:
            return self._summary_response(payload, executed, last_tool_name, last_data)

    def _guard_tool_call(
        self,
        *,
        tool_name: str,
        user_text: str,
        executed_write_tools: set[str],
    ) -> None:
        keywords = _WRITE_TOOL_KEYWORDS.get(tool_name)
        if keywords is None:
            return
        if tool_name in executed_write_tools:
            raise ValueError(f"写操作工具 {tool_name} 在一次 multi-step 请求中最多执行一次。")
        normalized = user_text.lower()
        if not any(keyword.lower() in normalized for keyword in keywords):
            raise ValueError(f"写操作工具 {tool_name} 需要用户明确表达执行意图。")

    def _assistant_message(self, response: dict[str, Any]) -> dict[str, Any] | None:
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(message, dict):
            return message
        return None

    def _final_response(
        self,
        final_text: str,
        executed: list[AgentToolCall],
        last_tool_name: str | None,
        last_data: Any,
    ) -> AgentQueryResponse:
        return AgentQueryResponse(
            success=all(call.success for call in executed) if executed else True,
            intent="multi_step",
            chosen_tool=last_tool_name,
            tool_calls=executed,
            final_answer=final_text,
            data=last_data,
            error=None,
            routing_method="multi_step",
            answer=final_text,
            used_tool=last_tool_name,
        )

    def _summary_response(
        self,
        payload: AgentQueryRequest,
        executed: list[AgentToolCall],
        last_tool_name: str | None,
        last_data: Any,
    ) -> AgentQueryResponse:
        if last_tool_name is not None and last_data is not None:
            final_answer = build_final_answer(last_tool_name, last_data)
        else:
            errors = "；".join(
                f"{call.tool_name}: {call.error}" for call in executed if call.error
            )
            final_answer = f"多步执行未完成：{errors or '没有可用的工具结果。'}"
        return self._final_response(final_answer, executed, last_tool_name, last_data)
