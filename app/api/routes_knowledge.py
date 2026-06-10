from __future__ import annotations

from fastapi import APIRouter

from app.schemas.knowledge import KnowledgeArtifactRead, KnowledgeGenerateRequest
from app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
knowledge_service = KnowledgeService()


@router.post("/generate", response_model=KnowledgeArtifactRead)
def generate_knowledge(payload: KnowledgeGenerateRequest) -> KnowledgeArtifactRead:
    return knowledge_service.generate(payload)


@router.get("/latest", response_model=KnowledgeArtifactRead)
def get_latest_knowledge() -> KnowledgeArtifactRead:
    return knowledge_service.latest()


@router.get("/history", response_model=list[KnowledgeArtifactRead])
def list_knowledge_history() -> list[KnowledgeArtifactRead]:
    return knowledge_service.history()
