from __future__ import annotations

from fastapi import APIRouter

from app.schemas.paper import (
    PaperAcceptRequest,
    PaperIngestRequest,
    PaperRead,
    PaperSearchHistoryRead,
    PaperSearchRequest,
)
from app.services.paper_service import PaperService

router = APIRouter(prefix="/papers", tags=["papers"])
paper_service = PaperService()


@router.post("/search", response_model=list[PaperRead])
def search_papers(payload: PaperSearchRequest) -> list[PaperRead]:
    return paper_service.search_and_store(payload)


@router.get("/search-history", response_model=list[PaperSearchHistoryRead])
def list_search_history() -> list[PaperSearchHistoryRead]:
    return paper_service.list_search_history()


@router.get("", response_model=list[PaperRead])
def list_papers(status: str | None = None) -> list[PaperRead]:
    return paper_service.list_papers(status=status)


@router.post("/accept", response_model=PaperRead)
def accept_paper(payload: PaperAcceptRequest) -> PaperRead:
    return paper_service.accept_paper(payload)


@router.post("/ingest", response_model=PaperRead)
def ingest_paper(payload: PaperIngestRequest) -> PaperRead:
    return paper_service.ingest_paper(payload)


@router.get("/accepted", response_model=list[PaperRead])
def list_accepted_papers() -> list[PaperRead]:
    return paper_service.list_accepted()


@router.get("/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: int) -> PaperRead:
    return paper_service.get_paper(paper_id)


@router.post("/{paper_id}/save", response_model=PaperRead)
def save_paper(paper_id: int) -> PaperRead:
    return paper_service.save_paper(paper_id)
