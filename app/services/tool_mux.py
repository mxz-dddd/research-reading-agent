from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


READ_ONLY_PREFIXES = ("get", "list", "read", "search", "status")
MUTATING_PREFIXES = (
    "create",
    "update",
    "delete",
    "write",
    "accept",
    "ingest",
    "generate",
    "run",
)


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool: str
    success: bool
    result: Any = None
    error: str | None = None
    cached: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    func: Callable[..., Any]
    description: str = ""
    read_only: bool = False


def infer_read_only(tool_name: str) -> bool:
    normalized = tool_name.strip().lower()
    prefix = normalized.split("_", 1)[0]
    if prefix in MUTATING_PREFIXES:
        return False
    return prefix in READ_ONLY_PREFIXES


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        description: str = "",
        read_only: bool | None = None,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("tool name must be a non-empty string")
        if not callable(func):
            raise TypeError("func must be callable")

        tool_name = name.strip()
        self._tools[tool_name] = ToolDefinition(
            name=tool_name,
            func=func,
            description=description,
            read_only=infer_read_only(tool_name) if read_only is None else read_only,
        )

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "read_only": tool.read_only,
            }
            for tool in sorted(self._tools.values(), key=lambda item: item.name)
        ]


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class ToolCache:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 256) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._read_only_tools: set[str] = set()
        self.hits = 0
        self.misses = 0

    def set_tool_read_only(self, tool_name: str, read_only: bool) -> None:
        if read_only:
            self._read_only_tools.add(tool_name)
        else:
            self._read_only_tools.discard(tool_name)

    def make_key(self, tool_name: str, arguments: dict[str, Any] | None) -> str:
        payload = {
            "tool": tool_name,
            "arguments": arguments or {},
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, tool_name: str, arguments: dict[str, Any] | None) -> Any | None:
        if self.ttl_seconds <= 0 or tool_name not in self._read_only_tools:
            self.misses += 1
            return None

        key = self.make_key(tool_name, arguments)
        entry = self._entries.get(key)
        now = time.time()
        if entry is None:
            self.misses += 1
            return None
        if entry.expires_at <= now:
            self._entries.pop(key, None)
            self.misses += 1
            return None

        self._entries.move_to_end(key)
        self.hits += 1
        return entry.value

    def set(self, tool_name: str, arguments: dict[str, Any] | None, result: ToolResult) -> None:
        if (
            self.ttl_seconds <= 0
            or tool_name not in self._read_only_tools
            or not result.success
        ):
            return

        key = self.make_key(tool_name, arguments)
        self._entries[key] = _CacheEntry(
            value=result.result,
            expires_at=time.time() + self.ttl_seconds,
        )
        self._entries.move_to_end(key)
        self._evict_expired()
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def stats(self) -> dict[str, Any]:
        self._evict_expired()
        lookups = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "ttl_seconds": self.ttl_seconds,
            "max_entries": self.max_entries,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hits / lookups if lookups else 0,
        }

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)


class ToolMux:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        cache: ToolCache | None = None,
        max_concurrency: int = 5,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.registry = registry or ToolRegistry()
        self.cache = cache or ToolCache()
        self.max_concurrency = max_concurrency
        self._sync_cache_policy()

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._sync_cache_policy()
        started = time.perf_counter()
        args = arguments or {}
        try:
            tool = self.registry.get(tool_name)
        except KeyError:
            return ToolResult(
                tool=tool_name,
                success=False,
                error=f"unknown tool: {tool_name}",
                duration_ms=self._duration_ms(started),
            ).to_dict()

        if tool.read_only:
            cached = self.cache.get(tool_name, args)
            if cached is not None:
                return ToolResult(
                    tool=tool_name,
                    success=True,
                    result=cached,
                    cached=True,
                    duration_ms=self._duration_ms(started),
                ).to_dict()

        try:
            result = await self._invoke(tool.func, args)
            tool_result = ToolResult(
                tool=tool_name,
                success=True,
                result=result,
                duration_ms=self._duration_ms(started),
            )
            self.cache.set(tool_name, args, tool_result)
            return tool_result.to_dict()
        except Exception as exc:
            return ToolResult(
                tool=tool_name,
                success=False,
                error=str(exc),
                duration_ms=self._duration_ms(started),
            ).to_dict()

    async def parallel(self, calls: list[dict[str, Any] | ToolCall]) -> dict[str, Any]:
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(raw_call: dict[str, Any] | ToolCall) -> dict[str, Any]:
            started = time.perf_counter()
            try:
                call = self._normalize_call(raw_call)
            except (TypeError, ValueError) as exc:
                return ToolResult(
                    tool=self._raw_tool_name(raw_call),
                    success=False,
                    error=str(exc),
                    duration_ms=self._duration_ms(started),
                ).to_dict()

            async with semaphore:
                return await self.call(call.tool, call.arguments)

        results = await asyncio.gather(*(run_one(call) for call in calls))
        return self._fanout_response(results)

    async def batch(self, tool_name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        calls = [ToolCall(tool=tool_name, arguments=item) for item in items]
        return await self.parallel(calls)

    async def _invoke(self, func: Callable[..., Any], arguments: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(func):
            return await func(**arguments)
        return await asyncio.to_thread(func, **arguments)

    def _sync_cache_policy(self) -> None:
        for tool in self.registry.list_tools():
            self.cache.set_tool_read_only(tool["name"], bool(tool["read_only"]))

    def _normalize_call(self, raw_call: dict[str, Any] | ToolCall) -> ToolCall:
        if isinstance(raw_call, ToolCall):
            return raw_call
        if not isinstance(raw_call, dict):
            raise TypeError("each call must be a dict or ToolCall")
        tool_name = raw_call.get("tool")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError('each call must include a non-empty "tool"')
        arguments = raw_call.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError('"arguments" must be a dict')
        return ToolCall(tool=tool_name, arguments=arguments)

    def _raw_tool_name(self, raw_call: dict[str, Any] | ToolCall) -> str:
        if isinstance(raw_call, ToolCall):
            return raw_call.tool
        if isinstance(raw_call, dict) and isinstance(raw_call.get("tool"), str):
            return raw_call["tool"]
        return "<invalid>"

    def _fanout_response(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        failed_indexes = [
            index for index, result in enumerate(results) if not result.get("success")
        ]
        failed = len(failed_indexes)
        return {
            "status": "completed" if failed == 0 else "partial",
            "results": results,
            "succeeded": len(results) - failed,
            "failed": failed,
            "failed_indexes": failed_indexes,
        }

    def _duration_ms(self, started: float) -> int:
        return round((time.perf_counter() - started) * 1000)
