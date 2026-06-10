from __future__ import annotations

from app.repositories.paper_repo import PaperRepository
from app.schemas.paper import PaperRead


def save_paper(paper_id: int) -> PaperRead:
    # 保留第一阶段 save 语义，同时把论文推进到“已确认可用”流程。
    return PaperRepository().accept(paper_id=paper_id)
