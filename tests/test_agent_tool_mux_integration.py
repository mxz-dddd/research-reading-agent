from __future__ import annotations

import asyncio

from app.services.agent_service import AgentService
from app.services.tool_mux import ToolMux, ToolRegistry


def run(coro):
    return asyncio.run(coro)


def test_agent_service_exposes_tool_mux_parallel_entrypoint() -> None:
    service = AgentService()

    registry = ToolRegistry()
    registry.register("ok", lambda x: {"x": x}, read_only=True)
    service.tool_mux = ToolMux(registry=registry)

    assert hasattr(service, "tool_mux")
    assert hasattr(service, "run_parallel_tools")

    result = run(
        service.run_parallel_tools(
            [
                {"tool": "ok", "arguments": {"x": 1}},
                {"tool": "missing", "arguments": {}},
            ]
        )
    )

    assert result["status"] == "partial"
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["failed_indexes"] == [1]
