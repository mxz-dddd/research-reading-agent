from __future__ import annotations

from typing import Any

from app.agent.orchestrator import AgentOrchestrator
from app.agent.tool_mux_factory import build_research_tool_mux
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse
from app.services.tool_mux import ToolMux


class AgentService:
    def __init__(
        self,
        orchestrator: AgentOrchestrator | None = None,
        tool_mux: ToolMux | None = None,
    ) -> None:
        self.orchestrator = orchestrator if orchestrator is not None else AgentOrchestrator()
        self.tool_mux = tool_mux if tool_mux is not None else build_research_tool_mux()

    def query(self, payload: AgentQueryRequest) -> AgentQueryResponse:
        return self.orchestrator.query(payload)

    async def run_parallel_tools(self, calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Run multiple registered tools concurrently through ToolMux."""
        return await self.tool_mux.parallel(calls)
