"""Shared Responses API client for LLM-backed features."""

from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from app.core.config import settings


class LLMClientError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 300,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.model = model or settings.openai_model
        self.base_url = (base_url if base_url is not None else settings.openai_base_url).rstrip("/")
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    @property
    def responses_url(self) -> str:
        return f"{self.base_url}/responses"

    def responses(
        self,
        prompt: str,
        *,
        instructions: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Call the configured Responses API and return the raw response JSON."""
        if not self.is_configured():
            raise LLMClientError("OPENAI_API_KEY or OPENAI_BASE_URL is not configured")

        body: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            "stream": False,
        }
        if tools:
            body["tools"] = self._normalize_responses_tools(tools)
        if temperature is not None:
            body["temperature"] = temperature

        return self._post_json(body)

    def responses_text(
        self,
        prompt: str,
        *,
        instructions: str,
        temperature: float | None = None,
    ) -> str:
        data = self.responses(
            prompt,
            instructions=instructions,
            temperature=temperature,
        )
        text = self.extract_text(data)
        if not text:
            raise LLMClientError("LLM returned empty content")
        return text

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Compatibility wrapper that sends chat-shaped prompts through Responses."""
        del tool_choice
        instructions, prompt = self._messages_to_responses_input(messages)
        data = self.responses(
            prompt,
            instructions=instructions,
            tools=tools,
            temperature=temperature,
        )
        return self._to_chat_compatible_response(data)

    def chat_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
    ) -> str:
        """Return the first text response for chat-shaped caller code."""
        data = self.chat(messages, temperature=temperature)
        content = self.extract_text(data)
        if not content:
            raise LLMClientError("LLM returned empty content")
        return content

    @staticmethod
    def extract_tool_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract function/tool calls from Responses or compatibility responses."""
        calls: list[dict[str, Any]] = []
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            message = None
        if isinstance(message, dict):
            for item in message.get("tool_calls") or []:
                function = item.get("function") or {}
                name = function.get("name")
                raw_args = function.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (json.JSONDecodeError, TypeError, ValueError):
                    args = {}
                if name:
                    calls.append({"id": item.get("id"), "name": name, "arguments": args})

        for item in data.get("output", []):
            if item.get("type") not in {"function_call", "tool_call"}:
                continue
            name = item.get("name")
            raw_args = item.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (json.JSONDecodeError, TypeError, ValueError):
                args = {}
            if name:
                calls.append(
                    {
                        "id": item.get("call_id") or item.get("id"),
                        "name": name,
                        "arguments": args,
                    }
                )
        return calls

    @staticmethod
    def extract_text(data: dict[str, Any]) -> str | None:
        if data.get("output_text"):
            text = str(data["output_text"]).strip()
            if text:
                return text

        parts: list[str] = []
        for item in data.get("output", []):
            if item.get("type") in {"message", "assistant_message"}:
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"}:
                        parts.append(str(content.get("text", "")))
            elif item.get("type") in {"output_text", "text"}:
                parts.append(str(item.get("text", "")))
        text = "".join(parts).strip()
        if text:
            return text

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if isinstance(content, str) and content.strip():
            return content.strip()
        return None

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.responses_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc

    @staticmethod
    def _messages_to_responses_input(messages: list[dict[str, Any]]) -> tuple[str, str]:
        system_parts: list[str] = []
        prompt_parts: list[str] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = message.get("content")
            if content is None:
                content_text = ""
            elif isinstance(content, str):
                content_text = content
            else:
                content_text = json.dumps(content, ensure_ascii=False, default=str)
            if role == "system":
                system_parts.append(content_text)
            else:
                prompt_parts.append(f"{role}: {content_text}")
        return "\n\n".join(system_parts), "\n\n".join(prompt_parts)

    @staticmethod
    def _normalize_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                function = tool.get("function") or {}
                normalized.append(
                    {
                        "type": "function",
                        "name": function.get("name"),
                        "description": function.get("description", ""),
                        "parameters": function.get(
                            "parameters",
                            {"type": "object", "properties": {}},
                        ),
                    }
                )
            else:
                normalized.append(tool)
        return normalized

    def _to_chat_compatible_response(self, data: dict[str, Any]) -> dict[str, Any]:
        tool_calls = []
        for call in self.extract_tool_calls(data):
            tool_calls.append(
                {
                    "id": call.get("id") or call["name"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                    },
                }
            )
        if tool_calls:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": tool_calls,
                        }
                    }
                ],
                "output": data.get("output", []),
            }
        text = self.extract_text(data)
        return {
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "output": data.get("output", []),
            "output_text": text,
        }

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())
