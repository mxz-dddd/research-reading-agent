import importlib
import re

from app.core.config import settings
from app.schemas.rag import RagSearchChunk


def _tokens(text: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text) if token.strip()
    }


class DeterministicReranker:
    def rerank(self, query: str, chunks: list[RagSearchChunk]) -> list[RagSearchChunk]:
        query_tokens = _tokens(query)
        query_lower = query.lower()
        reranked: list[RagSearchChunk] = []
        for chunk in chunks:
            content_tokens = _tokens(chunk.content)
            header_tokens = _tokens(
                (chunk.section_title or "") + "\n" + (chunk.contextual_header or "")
            )
            overlap = len(query_tokens.intersection(content_tokens))
            header_overlap = len(query_tokens.intersection(header_tokens))
            phrase_bonus = 1.0 if query_lower and query_lower in chunk.content.lower() else 0.0
            fused = chunk.retrieval_scores.get("rrf", chunk.score)
            rerank_score = fused + overlap * 0.25 + header_overlap * 0.15 + phrase_bonus
            reason = chunk.score_reason or ""
            detail = (
                f"rerank: fused={fused:.4f}, overlap={overlap}, "
                f"header_overlap={header_overlap}, phrase_bonus={phrase_bonus:.1f}"
            )
            chunk.rerank_score = round(rerank_score, 6)
            chunk.score_reason = f"{reason}；{detail}" if reason else detail
            reranked.append(chunk)
        reranked.sort(
            key=lambda item: (item.rerank_score or 0.0, item.score, item.chunk_id), reverse=True
        )
        return reranked


class CrossEncoderReranker:
    """Optional cross-encoder reranker loaded only when explicitly selected."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.rag_cross_encoder_model
        try:
            module = importlib.import_module("sentence_transformers")
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. Install the optional dependency with: "
                "pip install -r requirements-paperweave-reranker.txt"
            ) from exc
        self.model = module.CrossEncoder(self.model_name)

    def rerank(self, query: str, chunks: list[RagSearchChunk]) -> list[RagSearchChunk]:
        if not chunks:
            return chunks
        scores = self.model.predict([(query, chunk.content) for chunk in chunks])
        for chunk, score in zip(chunks, scores, strict=False):
            value = float(score)
            chunk.rerank_score = round(value, 6)
            detail = f"cross-encoder({self.model_name}) score={value:.4f}"
            chunk.score_reason = f"{chunk.score_reason}；{detail}" if chunk.score_reason else detail
        chunks.sort(
            key=lambda item: (item.rerank_score or 0.0, item.score, item.chunk_id),
            reverse=True,
        )
        return chunks


def get_reranker(provider: str | None = None, model_name: str | None = None):
    provider_name = (provider or "deterministic").strip().lower().replace("_", "-")
    if provider_name == "cross-encoder":
        return CrossEncoderReranker(model_name=model_name), "cross-encoder"
    if provider_name == "deterministic":
        return DeterministicReranker(), "deterministic"
    raise ValueError(f"Unsupported reranker provider: {provider}")
