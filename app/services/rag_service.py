import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.rag.answer_synthesis import LLMAnswerSynthesizer
from app.rag.chunking import ContextualChunker
from app.rag.embeddings import get_embedding_provider
from app.rag.retrievers import HybridRetriever
from app.rag.sqlite_vector_store import SqliteVectorStore, build_provider_key
from app.repositories.paper_repo import PaperRepository
from app.repositories.rag_repo import RagChunkRepository
from app.repositories.rag_trace_repo import RagTraceRepository
from app.schemas.paper import PaperRead
from app.schemas.rag import (
    RagAnswerResponse,
    RagChunkCreate,
    RagIndexResponse,
    RagSearchChunk,
    RagSearchResponse,
    RagTraceCreate,
    RagTraceRead,
)
from app.services.context_service import ContextService

RAG_V1_WARNING = "RAG v1 基于本地关键词检索生成保守回答，不代表完整语义理解。"
RAG_V2_WARNING = (
    "RAG v2 使用 contextual chunk、hybrid retrieval、RRF fusion 和轻量 rerank 生成证据约束回答。"
)


class RagService:
    def __init__(self) -> None:
        self.paper_repo = PaperRepository()
        self.rag_repo = RagChunkRepository()
        self.trace_repo = RagTraceRepository()
        self.context_service = ContextService()
        self.answer_synthesizer = LLMAnswerSynthesizer()

    def index_paper_for_rag(
        self,
        paper_id: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        index_version: str = "hybrid_v2",
        chunker_version: str = "contextual_v1",
    ) -> RagIndexResponse:
        warnings: list[str] = []
        paper = self.paper_repo.get(int(paper_id))
        text, source_type, source_path, source_warning = self._load_paper_text(paper)
        if source_warning:
            warnings.append(source_warning)
        if not text.strip():
            return RagIndexResponse(
                success=False,
                paper_id=str(paper_id),
                chunk_count=0,
                warnings=warnings,
                error="没有可用于 RAG 索引的论文文本。",
            )

        chunker = ContextualChunker()
        chunks = chunker.split(
            text=text,
            paper_title=paper.title,
            source_type=source_type,
            source_path=source_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunker_version=chunker_version,
            index_version=index_version,
        )
        self.rag_repo.delete_chunks_by_paper_id(str(paper_id))
        embed_items: list[tuple[str, str]] = []
        for index, chunk in enumerate(chunks):
            chunk_id = f"paper-{paper_id}-{index}-{uuid4().hex[:8]}"
            self.rag_repo.create_chunk(
                RagChunkCreate(
                    chunk_id=chunk_id,
                    paper_id=str(paper_id),
                    source_type=source_type,
                    source_path=source_path,
                    chunk_index=index,
                    content=chunk["content"],
                    content_preview=self._preview(chunk["content"]),
                    metadata={
                        "paper_title": paper.title,
                        "ingest_status": paper.ingest_status,
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                    },
                    contextual_header=chunk["contextual_header"],
                    section_title=chunk["section_title"],
                    content_for_embedding=chunk["content_for_embedding"],
                    token_count=chunk["token_count"],
                    chunker_version=chunk["chunker_version"],
                    index_version=chunk["index_version"],
                )
            )
            embed_items.append((chunk_id, chunk["content_for_embedding"] or chunk["content"]))

        # 在索引期一次性预计算并缓存 embedding，检索时只读缓存，避免每次查询全量重算。
        precompute_warning = self._precompute_embeddings(embed_items)
        if precompute_warning:
            warnings.append(precompute_warning)

        return RagIndexResponse(
            success=True,
            paper_id=str(paper_id),
            chunk_count=len(chunks),
            warnings=warnings,
            error=None,
        )

    def search_rag(
        self,
        query: str,
        top_k: int = 5,
        paper_id: str | None = None,
        user_id: str = "default",
        session_id: str = "default",
        retrieval_mode: str | None = None,
        save_trace: bool = True,
    ) -> RagSearchResponse:
        if not query.strip():
            return RagSearchResponse(
                success=False,
                query=query,
                evidence_chunks=[],
                message="query 为空，无法执行 RAG 检索。",
                no_evidence=True,
                error="empty query",
            )

        mode = retrieval_mode or settings.rag_retrieval_mode
        chunks, pipeline = self._retrieve_chunks(
            query=query,
            top_k=top_k,
            paper_id=paper_id,
            retrieval_mode=mode,
        )
        context_pack = self.context_service.build_context_pack(
            query=query,
            mode="search",
            evidence_chunks=chunks,
            user_id=user_id,
            session_id=session_id,
            paper_id=paper_id,
        )
        message = None
        if not chunks:
            message = "当前已索引论文中没有找到足够依据。"
        trace_id = None
        trace_warning = None
        if save_trace:
            trace_id, trace_warning = self._save_trace(
                query=query,
                mode="search",
                paper_id=paper_id,
                top_k=top_k,
                evidence_chunks=chunks,
                answer=None,
                metadata={
                    "source": "rag_search",
                    "message": message,
                    "score_summary": self._score_summary(chunks),
                    "pipeline": pipeline,
                    "context_pack_id": context_pack.context_pack_id,
                    "retrieval_mode": mode,
                },
            )

        return RagSearchResponse(
            success=True,
            query=query,
            evidence_chunks=chunks,
            message=message,
            no_evidence=not bool(chunks),
            error=None,
            trace_id=trace_id,
            trace_warning=trace_warning,
            retrieval_mode=mode,
            context_pack_id=context_pack.context_pack_id,
            context_pack=context_pack.model_dump(),
            pipeline=pipeline,
        )

    def answer_with_rag(
        self,
        query: str,
        top_k: int = 5,
        paper_id: str | None = None,
        user_id: str = "default",
        session_id: str = "default",
        retrieval_mode: str | None = None,
        save_trace: bool = True,
    ) -> RagAnswerResponse:
        if not query.strip():
            return RagAnswerResponse(
                success=False,
                query=query,
                answer="query 为空，无法执行 RAG 回答。",
                evidence_chunks=[],
                warning=self._warning_for_mode(retrieval_mode or settings.rag_retrieval_mode),
                no_evidence=True,
                error="empty query",
            )

        mode = retrieval_mode or settings.rag_retrieval_mode
        search_result = self.search_rag(
            query=query,
            top_k=top_k,
            paper_id=paper_id,
            user_id=user_id,
            session_id=session_id,
            retrieval_mode=mode,
            save_trace=False,
        )
        warning = self._warning_for_mode(mode)
        if not search_result.evidence_chunks:
            answer = "当前已索引论文中没有检索到足够证据，无法基于文档回答该问题。"
            trace_id = None
            trace_warning = None
            if save_trace:
                trace_id, trace_warning = self._save_trace(
                    query=query,
                    mode="answer",
                    paper_id=paper_id,
                    top_k=top_k,
                    evidence_chunks=[],
                    answer=answer,
                    metadata={
                        "source": "rag_answer",
                        "warning": warning,
                        "score_summary": self._score_summary([]),
                        "pipeline": search_result.pipeline,
                        "context_pack_id": search_result.context_pack_id,
                        "retrieval_mode": mode,
                    },
                )
            return RagAnswerResponse(
                success=search_result.success,
                query=query,
                answer=answer,
                evidence_chunks=[],
                warning=warning,
                no_evidence=True,
                error=search_result.error,
                trace_id=trace_id,
                trace_warning=trace_warning,
                retrieval_mode=mode,
                context_pack_id=search_result.context_pack_id,
                context_pack=search_result.context_pack,
                pipeline=search_result.pipeline,
                answer_mode="refusal_no_evidence",
            )

        answer, answer_mode, answer_model, citations = self._build_answer(
            query=query,
            mode=mode,
            warning=warning,
            evidence_chunks=search_result.evidence_chunks,
        )
        trace_id = None
        trace_warning = None
        if save_trace:
            trace_id, trace_warning = self._save_trace(
                query=query,
                mode="answer",
                paper_id=paper_id,
                top_k=top_k,
                evidence_chunks=search_result.evidence_chunks,
                answer=answer,
                metadata={
                    "source": "rag_answer",
                    "warning": warning,
                    "score_summary": self._score_summary(search_result.evidence_chunks),
                    "pipeline": search_result.pipeline,
                    "context_pack_id": search_result.context_pack_id,
                    "retrieval_mode": mode,
                    "answer_mode": answer_mode,
                    "answer_model": answer_model,
                    "citations": citations,
                },
            )

        return RagAnswerResponse(
            success=True,
            query=query,
            answer=answer,
            evidence_chunks=search_result.evidence_chunks,
            warning=warning,
            no_evidence=False,
            error=None,
            trace_id=trace_id,
            trace_warning=trace_warning,
            retrieval_mode=mode,
            context_pack_id=search_result.context_pack_id,
            context_pack=search_result.context_pack,
            pipeline=search_result.pipeline,
            answer_mode=answer_mode,
            answer_model=answer_model,
            citations=citations,
        )

    def _build_answer(
        self,
        *,
        query: str,
        mode: str,
        warning: str,
        evidence_chunks: list[RagSearchChunk],
    ) -> tuple[str, str, str | None, dict[str, Any] | None]:
        """Use citation-aware LLM synthesis when configured, otherwise keep the template answer."""
        answer_mode = "template"
        citations: dict[str, Any] | None = None
        if self.answer_synthesizer.should_use_llm():
            result = self.answer_synthesizer.synthesize(
                query=query,
                evidence_chunks=evidence_chunks,
            )
            if result is None:
                answer_mode = "template_fallback_llm_error"
            elif result["valid"]:
                return result["answer"], "llm", result["model"], result["citations"]
            else:
                answer_mode = "template_fallback_invalid_citations"
                citations = result["citations"]
        return (
            self._template_answer(mode=mode, warning=warning, evidence_chunks=evidence_chunks),
            answer_mode,
            None,
            citations,
        )

    def _template_answer(
        self,
        *,
        mode: str,
        warning: str,
        evidence_chunks: list[RagSearchChunk],
    ) -> str:
        intro = (
            "以下回答基于 contextual hybrid RAG 检索到的 evidence："
            if mode == "hybrid"
            else "以下回答基于已索引论文片段："
        )
        lines = [intro, "命中的 evidence 主要包括："]
        for index, chunk in enumerate(evidence_chunks, start=1):
            terms = ", ".join(chunk.matched_terms) if chunk.matched_terms else "未记录命中词"
            retrieval_scores = (
                ", ".join(f"{key}={value:.4f}" for key, value in chunk.retrieval_scores.items())
                or "未记录"
            )
            rerank = chunk.rerank_score if chunk.rerank_score is not None else "未启用"
            lines.append(
                f"[Evidence {index}] P{chunk.paper_id} / chunk {chunk.chunk_index} "
                f"/ section={chunk.section_title or 'Unknown'} "
                f"(score={chunk.score}, matched_terms={terms}, retrieval_scores={retrieval_scores}, "
                f"rerank_score={rerank})：{chunk.content_preview}"
            )
        lines.extend(
            [
                "",
                "保守结论：这些片段可以作为回答该问题的局部依据，但需要结合完整论文上下文复核。",
                warning,
            ]
        )
        return "\n".join(lines)

    def get_latest_traces(self, limit: int = 10) -> list[RagTraceRead]:
        return self.trace_repo.get_latest(limit=limit)

    def get_trace_detail(self, trace_id: str) -> RagTraceRead | None:
        return self.trace_repo.get_by_trace_id(trace_id)

    def list_traces_by_paper(self, paper_id: str, limit: int = 10) -> list[RagTraceRead]:
        return self.trace_repo.list_by_paper_id(paper_id=str(paper_id), limit=limit)

    def _load_paper_text(self, paper: PaperRead) -> tuple[str, str, str | None, str | None]:
        if paper.local_text_path:
            path = Path(paper.local_text_path)
            if path.exists():
                return path.read_text(encoding="utf-8"), "local_text", str(path), None
            return "", "local_text", str(path), f"local_text_path 不存在：{path}"

        if paper.local_summary_path:
            path = Path(paper.local_summary_path)
            if path.exists():
                return (
                    path.read_text(encoding="utf-8"),
                    "local_summary",
                    str(path),
                    "未找到 local_text_path，已使用 local_summary_path。",
                )

        if paper.deep_summary:
            return paper.deep_summary, "deep_summary", None, "未找到本地文本，已使用 deep_summary。"
        if paper.abstract_summary:
            return (
                paper.abstract_summary,
                "abstract_summary",
                None,
                "未找到本地文本，已使用 abstract_summary。",
            )
        if paper.abstract:
            return paper.abstract, "abstract", None, "未找到本地文本，已使用 abstract。"
        raise HTTPException(status_code=400, detail="该论文没有可用于 RAG 索引的文本。")

    def _split_text(self, text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        safe_overlap = min(chunk_overlap, max(chunk_size - 1, 0))
        step = max(1, chunk_size - safe_overlap)
        chunks: list[str] = []
        for start in range(0, len(normalized), step):
            chunk = normalized[start : start + chunk_size].strip()
            if chunk:
                chunks.append(chunk)
            if start + chunk_size >= len(normalized):
                break
        return chunks

    def _preview(self, text: str, max_chars: int = 240) -> str:
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    def _precompute_embeddings(self, items: list[tuple[str, str]]) -> str | None:
        """索引期预计算 chunk embedding 并写入本地缓存（rag_embeddings）。

        失败不影响索引结果，只会让首次检索退回即时计算，因此仅返回一条提示。
        """
        if not items:
            return None
        try:
            provider = get_embedding_provider(
                provider=getattr(settings, "rag_embedding_provider", "hash"),
                dim=getattr(settings, "rag_embedding_dim", 256),
                model_name=getattr(settings, "rag_sentence_transformers_model", None),
                device=getattr(settings, "rag_sentence_transformers_device", "auto"),
                batch_size=getattr(settings, "rag_embedding_batch_size", 32),
            )
            texts = [text for _chunk_id, text in items]
            embed_texts = getattr(provider, "embed_texts", None)
            vectors = (
                embed_texts(texts)
                if callable(embed_texts)
                else [provider.embed_text(text) for text in texts]
            )
            provider_key = build_provider_key(provider.metadata())
            SqliteVectorStore().upsert_vectors(
                provider_key,
                [
                    (chunk_id, vector)
                    for (chunk_id, _text), vector in zip(items, vectors, strict=False)
                ],
            )
        except Exception as exc:  # noqa: BLE001 - 预计算属于最佳努力，失败可降级
            return f"embedding 预计算失败（不影响检索，仅首次查询较慢）：{exc}"
        return None

    def _save_trace(
        self,
        *,
        query: str,
        mode: str,
        paper_id: str | None,
        top_k: int,
        evidence_chunks: list[RagSearchChunk],
        answer: str | None,
        metadata: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        trace_id = f"trace_{uuid4().hex[:12]}"
        try:
            self.trace_repo.create_trace(
                RagTraceCreate(
                    trace_id=trace_id,
                    query=query,
                    mode=mode,
                    paper_id=paper_id,
                    top_k=top_k,
                    hit_count=len(evidence_chunks),
                    no_evidence=not bool(evidence_chunks),
                    answer=answer,
                    evidence=[chunk.model_dump() for chunk in evidence_chunks],
                    metadata=metadata,
                )
            )
            return trace_id, None
        except Exception as exc:
            return None, f"rag trace persistence failed: {exc}"

    def _score_summary(self, chunks: list[RagSearchChunk]) -> dict[str, Any]:
        if not chunks:
            return {"hit_count": 0, "max_score": 0}
        return {
            "hit_count": len(chunks),
            "max_score": max(chunk.score for chunk in chunks),
            "matched_terms": sorted({term for chunk in chunks for term in chunk.matched_terms}),
        }

    def _retrieve_chunks(
        self,
        *,
        query: str,
        top_k: int,
        paper_id: str | None,
        retrieval_mode: str,
    ) -> tuple[list[RagSearchChunk], dict[str, Any]]:
        if retrieval_mode == "keyword":
            chunks = self.rag_repo.search_chunks(query=query, top_k=top_k, paper_id=paper_id)
            return chunks, {
                "retrieval_mode": "keyword",
                "sparse_candidate_count": len(chunks),
                "dense_candidate_count": 0,
                "fused_candidate_count": len(chunks),
                "rerank_enabled": False,
            }
        retriever = HybridRetriever(self.rag_repo, settings)
        return retriever.search(query=query, top_k=top_k, paper_id=paper_id)

    def _warning_for_mode(self, retrieval_mode: str) -> str:
        return RAG_V2_WARNING if retrieval_mode == "hybrid" else RAG_V1_WARNING
