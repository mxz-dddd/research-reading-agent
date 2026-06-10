from __future__ import annotations

from fastapi import APIRouter

from app.schemas.innovation import InnovationArtifactRead, InnovationGenerateRequest
from app.services.innovation_service import InnovationService

router = APIRouter(prefix="/innovation", tags=["innovation"])
innovation_service = InnovationService()


@router.post("/generate", response_model=InnovationArtifactRead)
def generate_innovation(payload: InnovationGenerateRequest) -> InnovationArtifactRead:
    return innovation_service.generate(payload)


@router.get("/latest", response_model=InnovationArtifactRead)
def get_latest_innovation() -> InnovationArtifactRead:
    return innovation_service.latest()


@router.get("/history", response_model=list[InnovationArtifactRead])
def list_innovation_history() -> list[InnovationArtifactRead]:
    return innovation_service.history()
