from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.repositories.context_repo import ContextPackRepository, estimate_tokens
from app.repositories.paper_repo import PaperRepository
from app.repositories.session_repo import SessionStateRepository
from app.schemas.context import ContextItem, ContextPackRead
from app.schemas.rag import RagSearchChunk


class ContextService:
    def __init__(self) -> None:
        self.context_repo = ContextPackRepository()
        self.session_repo = SessionStateRepository()
        self.paper_repo = PaperRepository()

    def build_context_pack(
        self,
        query: str,
        mode: str,
        evidence_chunks: list[RagSearchChunk],
        user_id: str = "default",
        session_id: str = "default",
        paper_id: str | None = None,
        token_budget: int | None = None,
    ) -> ContextPackRead:
        budget = token_budget or settings.rag_context_token_budget
        items: list[ContextItem] = []

        active_paper = self._active_paper_item(paper_id)
        if active_paper:
            items.append(active_paper)

        recent = self._recent_search_item(user_id=user_id, session_id=session_id)
        if recent:
            items.append(recent)

        for chunk in evidence_chunks:
            content = chunk.content
            if chunk.contextual_header:
                content = f"{chunk.contextual_header}\n{chunk.content_preview or chunk.content}"
            items.append(
                ContextItem(
                    item_type="rag_evidence",
                    source_type="rag_chunk",
                    source_id=chunk.chunk_id,
                    content=content,
                    score=chunk.rerank_score if chunk.rerank_score is not None else chunk.score,
                    reason=chunk.score_reason,
                    metadata={
                        "paper_id": chunk.paper_id,
                        "chunk_index": chunk.chunk_index,
                        "section_title": chunk.section_title,
                        "retrieval_scores": chunk.retrieval_scores,
                        "score_reason": chunk.score_reason,
                    },
                )
            )

        packed_items = self._fit_budget(query=query, items=items, token_budget=budget)
        return self.context_repo.create_context_pack(
            user_id=user_id,
            session_id=session_id,
            query=query,
            mode=mode,
            items=packed_items,
            paper_id=paper_id,
            token_budget=budget,
        )

    def _recent_search_item(self, *, user_id: str, session_id: str) -> ContextItem | None:
        state = self.session_repo.get_state(user_id, session_id)
        recent = state.get("recent_search_results") or []
        if not recent:
            return None
        compact = recent[-10:]
        return ContextItem(
            item_type="session_recent_search_results",
            source_type="session_state",
            content=json.dumps(compact, ensure_ascii=False),
            reason="来自当前会话最近一次论文搜索结果。",
            metadata={"count": len(compact)},
        )

    def _active_paper_item(self, paper_id: str | None) -> ContextItem | None:
        if not paper_id:
            return None
        try:
            paper = self.paper_repo.get(int(paper_id))
        except (HTTPException, ValueError):
            return None
        data: dict[str, Any] = {
            "title": paper.title,
            "abstract": paper.abstract,
            "status": paper.status,
            "ingest_status": paper.ingest_status,
        }
        return ContextItem(
            item_type="active_paper",
            source_type="papers",
            source_id=str(paper_id),
            content=json.dumps(data, ensure_ascii=False),
            reason="当前 RAG 请求指定的论文。",
            metadata={"paper_id": str(paper_id)},
        )

    def _fit_budget(
        self,
        *,
        query: str,
        items: list[ContextItem],
        token_budget: int,
    ) -> list[ContextItem]:
        used = estimate_tokens(query)
        packed: list[ContextItem] = []
        for item in items:
            item_tokens = estimate_tokens(item.content)
            if used + item_tokens <= token_budget:
                packed.append(item)
                used += item_tokens
                continue
            if item.item_type == "session_recent_search_results":
                room_chars = max(0, (token_budget - used) * 4)
                if room_chars > 40:
                    packed.append(item.model_copy(update={"content": item.content[:room_chars]}))
                    used = token_budget
            break
        return packed
