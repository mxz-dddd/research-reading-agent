"""OpenAI 兼容 Chat Completions 客户端。

供 PaperWeave LLM 回答合成与多步 Agent 共用。
仅使用标准库 urllib，base_url 可配置，便于接入 Ollama/vLLM/代理。
"""

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
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.model = model or settings.openai_model
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """调用 /chat/completions，返回原始响应 JSON；失败抛 LLMClientError。"""
        if not self.is_configured():
            raise LLMClientError("OPENAI_API_KEY is not configured")

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
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

    def chat_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
    ) -> str:
        """便捷方法：返回第一条 choice 的文本内容。"""
        data = self.chat(messages, temperature=temperature)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"Unexpected LLM response shape: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("LLM returned empty content")
        return content

    @staticmethod
    def extract_tool_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
        """从 chat/completions 响应中提取 tool_calls，返回 [{name, arguments(dict), id}]。"""
        calls: list[dict[str, Any]] = []
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return calls
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
        return calls

    @staticmethod
    def extract_text(data: dict[str, Any]) -> str | None:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(content, str) and content.strip():
            return content
        return None

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())
