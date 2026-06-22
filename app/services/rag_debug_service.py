import re
from typing import Any

from app.schemas.context import ContextPackRead
from app.schemas.rag import RagSearchChunk

EMPTY_CONTEXT_SUMMARY: dict[str, Any] = {
    "context_pack_id": None,
    "item_count": 0,
    "estimated_tokens": 0,
    "token_budget": 0,
    "item_type_counts": {},
}

EMPTY_PIPELINE_SUMMARY: dict[str, Any] = {
    "retrieval_mode": None,
    "sparse_candidate_count": 0,
    "dense_candidate_count": 0,
    "fused_candidate_count": 0,
    "rerank_enabled": False,
    "embedding_provider": None,
    "rrf_k": None,
}


class RagDebugService:
    def build_evidence_table(self, chunks: list[RagSearchChunk]) -> list[dict]:
        rows = []
        for rank, chunk in enumerate(chunks, start=1):
            retrieval_scores = getattr(chunk, "retrieval_scores", None) or {}
            rows.append(
                {
                    "rank": rank,
                    "chunk_id": getattr(chunk, "chunk_id", None),
                    "paper_id": getattr(chunk, "paper_id", None),
                    "section_title": getattr(chunk, "section_title", None),
                    "chunk_index": getattr(chunk, "chunk_index", None),
                    "score": self._float_or_default(getattr(chunk, "score", None)),
                    "sparse_score": self._float_or_default(retrieval_scores.get("sparse")),
                    "dense_score": self._float_or_default(retrieval_scores.get("dense")),
                    "rrf_score": self._float_or_default(retrieval_scores.get("rrf")),
                    "rerank_score": self._float_or_default(getattr(chunk, "rerank_score", None)),
                    "score_reason": getattr(chunk, "score_reason", None),
                    "content_preview": self._content_preview(chunk),
                }
            )
        return rows

    def build_context_summary(self, context_pack: ContextPackRead | dict | None) -> dict:
        if context_pack is None:
            return dict(EMPTY_CONTEXT_SUMMARY)

        items = self._read_value(context_pack, "items") or []
        item_count = self._read_value(context_pack, "item_count")
        if item_count is None:
            item_count = len(items)

        return {
            "context_pack_id": self._read_value(context_pack, "context_pack_id"),
            "item_count": item_count,
            "estimated_tokens": self._read_value(context_pack, "estimated_tokens") or 0,
            "token_budget": self._read_value(context_pack, "token_budget") or 0,
            "item_type_counts": self._item_type_counts(items),
        }

    def build_pipeline_summary(self, pipeline: dict | None) -> dict:
        if pipeline is None:
            return dict(EMPTY_PIPELINE_SUMMARY)

        return {
            "retrieval_mode": pipeline.get("retrieval_mode"),
            "sparse_candidate_count": pipeline.get("sparse_candidate_count", 0) or 0,
            "dense_candidate_count": pipeline.get("dense_candidate_count", 0) or 0,
            "fused_candidate_count": pipeline.get("fused_candidate_count", 0) or 0,
            "rerank_enabled": bool(pipeline.get("rerank_enabled", False)),
            "embedding_provider": pipeline.get("embedding_provider"),
            "rrf_k": pipeline.get("rrf_k"),
        }

    def _content_preview(self, chunk: RagSearchChunk) -> str:
        preview = getattr(chunk, "content_preview", None)
        if not preview:
            preview = getattr(chunk, "content", None) or getattr(chunk, "text", None) or ""
        return self._compact_text(str(preview))[:300]

    def _item_type_counts(self, items: list[Any]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            item_type = self._read_value(item, "item_type")
            if item_type:
                counts[item_type] = counts.get(item_type, 0) + 1
        return counts

    def _read_value(self, source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _float_or_default(self, value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _compact_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
