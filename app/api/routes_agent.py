from __future__ import annotations

from fastapi import APIRouter

from app.schemas.agent import AgentQueryRequest, AgentQueryResponse
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agent", tags=["agent"])
agent_service = AgentService()


@router.post("/query", response_model=AgentQueryResponse)
def query_agent(payload: AgentQueryRequest) -> AgentQueryResponse:
    return agent_service.query(payload)
