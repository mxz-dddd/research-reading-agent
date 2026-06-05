from app.agent.orchestrator import AgentOrchestrator
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse


class AgentService:
    def __init__(self) -> None:
        self.orchestrator = AgentOrchestrator()

    def query(self, payload: AgentQueryRequest) -> AgentQueryResponse:
        return self.orchestrator.query(payload)
