from __future__ import annotations

from app.repositories.paper_repo import PaperRepository
from app.schemas.paper import PaperRead


def list_papers(status: str | None = None) -> list[PaperRead]:
    return PaperRepository().list(status=status)
