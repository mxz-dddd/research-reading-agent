from __future__ import annotations

import math
from typing import Any

from app.repositories.rag_evidence_feedback_repo import (
    RAG_EVIDENCE_LABEL_BY_SCORE,
    RAG_EVIDENCE_SCORE_BY_LABEL,
    RagEvidenceFeedbackRepository,
)
from app.repositories.rag_feedback_repo import RAG_RELEVANCE_LABELS, RagFeedbackRepository
from app.repositories.rag_trace_repo import RagTraceRepository
from app.schemas.rag import RagEvidenceFeedbackRead, RagTraceFeedbackRead


class RagEvaluationService:
    def __init__(
        self,
        trace_repo: RagTraceRepository | None = None,
        feedback_repo: RagFeedbackRepository | None = None,
        evidence_feedback_repo: RagEvidenceFeedbackRepository | None = None,
    ) -> None:
        self.trace_repo = trace_repo if trace_repo is not None else RagTraceRepository()
        self.feedback_repo = feedback_repo if feedback_repo is not None else RagFeedbackRepository()
        self.evidence_feedback_repo = evidence_feedback_repo if evidence_feedback_repo is not None else RagEvidenceFeedbackRepository()

    def add_trace_feedback(
        self,
        *,
        trace_id: str,
        relevance_label: str,
        expected_terms: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        normalized_label = relevance_label.strip().lower()
        if normalized_label not in RAG_RELEVANCE_LABELS:
            return {
                "success": False,
                "data": None,
                "message": "relevance_label 非法。",
                "error": f"allowed labels: {', '.join(sorted(RAG_RELEVANCE_LABELS))}",
            }

        trace = self.trace_repo.get_by_trace_id(trace_id)
        if trace is None:
            return {
                "success": False,
                "data": None,
                "message": "没有找到对应的 RAG trace。",
                "error": "trace not found",
            }

        feedback = self.feedback_repo.create_feedback(
            trace_id=trace_id,
            relevance_label=normalized_label,
            expected_terms=expected_terms or [],
            notes=notes,
        )
        return {"success": True, "data": feedback, "message": None, "error": None}

    def get_rag_evaluation_summary(self) -> dict[str, Any]:
        trace_summary = self.trace_repo.summarize_traces()
        feedback_summary = self.feedback_repo.summarize_feedback()
        return {
            "success": True,
            "summary": {
                **trace_summary,
                **feedback_summary,
            },
        }

    def get_trace_evaluation_detail(self, trace_id: str) -> dict[str, Any]:
        trace = self.trace_repo.get_by_trace_id(trace_id)
        if trace is None:
            return {
                "success": False,
                "trace": None,
                "latest_feedback": None,
                "message": "没有找到对应的 RAG trace。",
                "error": "trace not found",
            }

        feedback: RagTraceFeedbackRead | None = self.feedback_repo.get_latest_feedback_for_trace(trace_id)
        message = None if feedback else "该 trace 暂无人工 feedback。"
        return {
            "success": True,
            "trace": trace,
            "latest_feedback": feedback,
            "message": message,
            "error": None,
        }

    def add_evidence_feedback(
        self,
        *,
        trace_id: str,
        chunk_id: str | None = None,
        rank: int | None = None,
        relevance_score: int,
        relevance_label: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        trace = self.trace_repo.get_by_trace_id(trace_id)
        if trace is None:
            return {
                "success": False,
                "data": None,
                "message": "没有找到对应的 RAG trace。",
                "error": "trace not found",
            }

        normalized = self._normalize_evidence_label(relevance_score, relevance_label)
        if normalized["error"]:
            return {"success": False, "data": None, "message": "evidence relevance 非法。", "error": normalized["error"]}

        evidence = trace.evidence or []
        resolved = self._resolve_evidence_ref(evidence=evidence, chunk_id=chunk_id, rank=rank)
        if resolved["error"]:
            return {"success": False, "data": None, "message": resolved["message"], "error": resolved["error"]}

        feedback = self.evidence_feedback_repo.create_evidence_feedback(
            trace_id=trace_id,
            chunk_id=resolved["chunk_id"],
            rank=resolved["rank"],
            relevance_score=normalized["score"],
            relevance_label=normalized["label"],
            notes=notes,
        )
        return {"success": True, "data": feedback, "message": None, "error": None}

    def get_evidence_evaluation_summary(
        self,
        trace_id: str | None = None,
        k_values: list[int] | None = None,
    ) -> dict[str, Any]:
        if trace_id is not None and self.trace_repo.get_by_trace_id(trace_id) is None:
            return {
                "success": False,
                "summary": {},
                "message": "没有找到对应的 RAG trace。",
                "error": "trace not found",
            }

        safe_k_values = sorted({k for k in (k_values or [1, 3, 5]) if k > 0}) or [1, 3, 5]
        latest = self.evidence_feedback_repo.latest_feedback_by_evidence(trace_id=trace_id)
        if not latest:
            return {
                "success": True,
                "summary": {
                    **self.evidence_feedback_repo.summarize_evidence_feedback(trace_id=trace_id),
                    **{f"recall_at_{k}": 0.0 for k in safe_k_values},
                    "mrr": 0.0,
                    "ndcg_at_5": 0.0,
                },
                "message": "暂无 evidence-level feedback，无法计算有效排序指标。",
            }

        by_trace: dict[str, list[RagEvidenceFeedbackRead]] = {}
        for feedback in latest.values():
            by_trace.setdefault(feedback.trace_id, []).append(feedback)
        for items in by_trace.values():
            items.sort(key=lambda item: item.rank)

        summary = self.evidence_feedback_repo.summarize_evidence_feedback(trace_id=trace_id)
        summary.update(self._ranking_metrics(by_trace=by_trace, k_values=safe_k_values))
        return {"success": True, "summary": summary, "message": None}

    def get_trace_evidence_evaluation(self, trace_id: str) -> dict[str, Any]:
        trace = self.trace_repo.get_by_trace_id(trace_id)
        if trace is None:
            return {
                "success": False,
                "trace_id": trace_id,
                "evidence": [],
                "message": "没有找到对应的 RAG trace。",
                "error": "trace not found",
            }

        latest = self.evidence_feedback_repo.latest_feedback_by_evidence(trace_id=trace_id)
        evidence_rows = []
        for index, evidence in enumerate(trace.evidence or [], start=1):
            chunk_id = str(evidence.get("chunk_id") or "")
            feedback = latest.get((trace_id, chunk_id))
            evidence_rows.append(
                {
                    "rank": index,
                    "chunk_id": chunk_id,
                    "score": evidence.get("score"),
                    "score_reason": evidence.get("score_reason"),
                    "content_preview": evidence.get("content_preview"),
                    "latest_feedback": feedback.model_dump() if feedback else None,
                }
            )
        message = None if latest else "该 trace 暂无 evidence-level feedback。"
        return {"success": True, "trace_id": trace_id, "evidence": evidence_rows, "message": message, "error": None}

    def _normalize_evidence_label(self, relevance_score: int, relevance_label: str | None) -> dict[str, Any]:
        if relevance_score not in RAG_EVIDENCE_LABEL_BY_SCORE:
            return {"score": relevance_score, "label": relevance_label, "error": "relevance_score must be 0, 1, or 2"}
        if relevance_label is None:
            return {"score": relevance_score, "label": RAG_EVIDENCE_LABEL_BY_SCORE[relevance_score], "error": None}
        normalized_label = relevance_label.strip().lower()
        if normalized_label not in RAG_EVIDENCE_SCORE_BY_LABEL:
            return {"score": relevance_score, "label": normalized_label, "error": "invalid relevance_label"}
        expected_score = RAG_EVIDENCE_SCORE_BY_LABEL[normalized_label]
        if expected_score != relevance_score:
            return {"score": relevance_score, "label": normalized_label, "error": "relevance_score and relevance_label mismatch"}
        return {"score": relevance_score, "label": normalized_label, "error": None}

    def _resolve_evidence_ref(
        self,
        *,
        evidence: list[dict[str, Any]],
        chunk_id: str | None,
        rank: int | None,
    ) -> dict[str, Any]:
        if not evidence:
            return {"message": "该 trace 没有 evidence chunks。", "error": "trace has no evidence"}

        if chunk_id:
            for index, item in enumerate(evidence, start=1):
                if str(item.get("chunk_id")) == str(chunk_id):
                    return {"chunk_id": str(chunk_id), "rank": int(rank or index), "error": None}
            return {"message": "chunk_id 不属于该 trace 的 evidence。", "error": "chunk not found in trace"}

        if rank is None:
            return {"message": "请提供 chunk_id 或 rank。", "error": "missing evidence reference"}
        if rank < 1 or rank > len(evidence):
            return {"message": "rank 超出该 trace 的 evidence 范围。", "error": "rank out of range"}
        item = evidence[rank - 1]
        return {"chunk_id": str(item.get("chunk_id")), "rank": rank, "error": None}

    def _ranking_metrics(
        self,
        *,
        by_trace: dict[str, list[RagEvidenceFeedbackRead]],
        k_values: list[int],
    ) -> dict[str, float]:
        trace_count = len(by_trace)
        metrics: dict[str, float] = {}
        for k in k_values:
            hits = sum(1 for items in by_trace.values() if any(item.rank <= k and item.relevance_score > 0 for item in items))
            metrics[f"recall_at_{k}"] = hits / trace_count if trace_count else 0.0

        reciprocal_ranks = []
        ndcgs = []
        for items in by_trace.values():
            relevant = [item for item in items if item.relevance_score > 0]
            if relevant:
                first_rank = min(item.rank for item in relevant)
                reciprocal_ranks.append(1 / first_rank)
            else:
                reciprocal_ranks.append(0.0)
            ndcgs.append(self._ndcg_at_k(items, k=5))
        metrics["mrr"] = sum(reciprocal_ranks) / trace_count if trace_count else 0.0
        metrics["ndcg_at_5"] = sum(ndcgs) / trace_count if trace_count else 0.0
        return metrics

    def _ndcg_at_k(self, items: list[RagEvidenceFeedbackRead], *, k: int) -> float:
        def gain(score: int, rank: int) -> float:
            return ((2**score) - 1) / math.log2(rank + 1)

        dcg = sum(gain(item.relevance_score, item.rank) for item in items if item.rank <= k)
        ideal_scores = sorted((item.relevance_score for item in items), reverse=True)[:k]
        idcg = sum(gain(score, rank) for rank, score in enumerate(ideal_scores, start=1))
        return dcg / idcg if idcg else 0.0
