from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

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


RAG_V1_WARNING = "RAG v1 基于本地关键词检索生成保守回答，不代表完整语义理解。"


class RagService:
    def __init__(self) -> None:
        self.paper_repo = PaperRepository()
        self.rag_repo = RagChunkRepository()
        self.trace_repo = RagTraceRepository()

    def index_paper_for_rag(
        self,
        paper_id: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
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

        chunks = self._split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.rag_repo.delete_chunks_by_paper_id(str(paper_id))
        for index, chunk in enumerate(chunks):
            self.rag_repo.create_chunk(
                RagChunkCreate(
                    chunk_id=f"paper-{paper_id}-{index}-{uuid4().hex[:8]}",
                    paper_id=str(paper_id),
                    source_type=source_type,
                    source_path=source_path,
                    chunk_index=index,
                    content=chunk,
                    content_preview=self._preview(chunk),
                    metadata={
                        "paper_title": paper.title,
                        "ingest_status": paper.ingest_status,
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                    },
                )
            )

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

        chunks = self.rag_repo.search_chunks(query=query, top_k=top_k, paper_id=paper_id)
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
                metadata={"source": "rag_search", "message": message, "score_summary": self._score_summary(chunks)},
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
        )

    def answer_with_rag(
        self,
        query: str,
        top_k: int = 5,
        paper_id: str | None = None,
        save_trace: bool = True,
    ) -> RagAnswerResponse:
        if not query.strip():
            return RagAnswerResponse(
                success=False,
                query=query,
                answer="query 为空，无法执行 RAG 回答。",
                evidence_chunks=[],
                warning=RAG_V1_WARNING,
                no_evidence=True,
                error="empty query",
            )

        search_result = self.search_rag(query=query, top_k=top_k, paper_id=paper_id, save_trace=False)
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
                        "warning": RAG_V1_WARNING,
                        "score_summary": self._score_summary([]),
                    },
                )
            return RagAnswerResponse(
                success=search_result.success,
                query=query,
                answer=answer,
                evidence_chunks=[],
                warning=RAG_V1_WARNING,
                no_evidence=True,
                error=search_result.error,
                trace_id=trace_id,
                trace_warning=trace_warning,
            )

        lines = [
            "以下回答基于已索引论文片段：",
            "命中的 evidence 主要包括：",
        ]
        for index, chunk in enumerate(search_result.evidence_chunks, start=1):
            terms = ", ".join(chunk.matched_terms) if chunk.matched_terms else "未记录命中词"
            lines.append(
                f"[Evidence {index}] P{chunk.paper_id} / chunk {chunk.chunk_index} "
                f"(score={chunk.score}, matched_terms={terms})：{chunk.content_preview}"
            )
        lines.extend(
            [
                "",
                "保守结论：这些片段可以作为回答该问题的局部依据，但需要结合完整论文上下文复核。",
                "RAG v1 使用关键词 / token overlap 检索，结果可能不等价于完整语义理解。",
            ]
        )
        answer = "\n".join(lines)
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
                    "warning": RAG_V1_WARNING,
                    "score_summary": self._score_summary(search_result.evidence_chunks),
                },
            )

        return RagAnswerResponse(
            success=True,
            query=query,
            answer=answer,
            evidence_chunks=search_result.evidence_chunks,
            warning=RAG_V1_WARNING,
            no_evidence=False,
            error=None,
            trace_id=trace_id,
            trace_warning=trace_warning,
        )

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
                return path.read_text(encoding="utf-8"), "local_summary", str(path), "未找到 local_text_path，已使用 local_summary_path。"

        if paper.deep_summary:
            return paper.deep_summary, "deep_summary", None, "未找到本地文本，已使用 deep_summary。"
        if paper.abstract_summary:
            return paper.abstract_summary, "abstract_summary", None, "未找到本地文本，已使用 abstract_summary。"
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
