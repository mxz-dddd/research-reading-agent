from typing import Any

from app.agent.orchestrator import AgentOrchestrator
from app.agent.tool_mux_factory import build_research_tool_mux
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse


class AgentService:
    def __init__(self) -> None:
        self.orchestrator = AgentOrchestrator()
        self.tool_mux = build_research_tool_mux()

    def query(self, payload: AgentQueryRequest) -> AgentQueryResponse:
        return self.orchestrator.query(payload)

    def query_with_route(
        self,
        payload: AgentQueryRequest,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        intent: str | None = None,
        routing_method: str = "context",
    ) -> AgentQueryResponse:
        return self.orchestrator.query_with_route(
            payload,
            tool_name=tool_name,
            arguments=arguments,
            intent=intent,
            routing_method=routing_method,
        )

    async def run_parallel_tools(self, calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Run multiple registered tools concurrently through ToolMux."""
        return await self.tool_mux.parallel(calls)
