from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GoldenQuery:
    query_id: str
    query: str
    paper_id: str | None = None
    expected_terms: list[str] = field(default_factory=list)
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_paper_ids: list[str] = field(default_factory=list)
    must_contain_any: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class RetrievalEvalResult:
    query_id: str
    query: str
    retrieval_mode: str
    top_k: int
    evidence_count: int
    matched_expected_terms: list[str]
    missing_expected_terms: list[str]
    matched_expected_chunk_ids: list[str]
    missing_expected_chunk_ids: list[str]
    matched_expected_paper_ids: list[str]
    missing_expected_paper_ids: list[str]
    recall_expected_terms: float
    recall_expected_chunk_ids: float
    recall_expected_paper_ids: float
    answer_contains_any: bool | None
    context_pack_id: str | None
    pipeline: dict[str, Any]
    error: str | None = None


class RagQualityEvalService:
    def load_golden_queries(self, path: str | Path) -> list[GoldenQuery]:
        queries: list[GoldenQuery] = []
        query_path = Path(path)
        try:
            lines = query_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ValueError(f"无法读取 golden queries 文件：{query_path}") from exc

        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"golden queries JSON 解析失败，行号：{line_number}") from exc
            if not isinstance(data, dict):
                raise ValueError(f"golden queries 每行必须是 JSON object，行号：{line_number}")
            if not data.get("query_id") or not data.get("query"):
                raise ValueError(f"query_id 和 query 为必填字段，行号：{line_number}")
            queries.append(
                GoldenQuery(
                    query_id=str(data["query_id"]),
                    query=str(data["query"]),
                    paper_id=str(data["paper_id"]) if data.get("paper_id") is not None else None,
                    expected_terms=self._list_of_str(data.get("expected_terms")),
                    expected_chunk_ids=self._list_of_str(data.get("expected_chunk_ids")),
                    expected_paper_ids=self._list_of_str(data.get("expected_paper_ids")),
                    must_contain_any=self._list_of_str(data.get("must_contain_any")),
                    notes=str(data.get("notes") or ""),
                )
            )
        return queries

    def evaluate_search_response(
        self,
        golden_query: GoldenQuery,
        response: Any,
        retrieval_mode: str,
        top_k: int,
    ) -> RetrievalEvalResult:
        evidence = self._extract_evidence(response)
        evidence_text = "\n".join(self._evidence_text(item) for item in evidence).lower()
        chunk_ids = {self._string_value(item, "chunk_id") for item in evidence}
        paper_ids = {self._string_value(item, "paper_id") for item in evidence}

        matched_terms = [term for term in golden_query.expected_terms if term.lower() in evidence_text]
        missing_terms = [term for term in golden_query.expected_terms if term not in matched_terms]
        matched_chunk_ids = [chunk_id for chunk_id in golden_query.expected_chunk_ids if chunk_id in chunk_ids]
        missing_chunk_ids = [chunk_id for chunk_id in golden_query.expected_chunk_ids if chunk_id not in chunk_ids]
        matched_paper_ids = [paper_id for paper_id in golden_query.expected_paper_ids if paper_id in paper_ids]
        missing_paper_ids = [paper_id for paper_id in golden_query.expected_paper_ids if paper_id not in paper_ids]

        return RetrievalEvalResult(
            query_id=golden_query.query_id,
            query=golden_query.query,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            evidence_count=len(evidence),
            matched_expected_terms=matched_terms,
            missing_expected_terms=missing_terms,
            matched_expected_chunk_ids=matched_chunk_ids,
            missing_expected_chunk_ids=missing_chunk_ids,
            matched_expected_paper_ids=matched_paper_ids,
            missing_expected_paper_ids=missing_paper_ids,
            recall_expected_terms=self._recall(matched_terms, golden_query.expected_terms),
            recall_expected_chunk_ids=self._recall(matched_chunk_ids, golden_query.expected_chunk_ids),
            recall_expected_paper_ids=self._recall(matched_paper_ids, golden_query.expected_paper_ids),
            answer_contains_any=None,
            context_pack_id=self._read_str(response, "context_pack_id"),
            pipeline=self._read_dict(response, "pipeline"),
        )

    def evaluate_answer_response(
        self,
        golden_query: GoldenQuery,
        response: Any,
        retrieval_result: RetrievalEvalResult | None = None,
    ) -> RetrievalEvalResult | dict:
        answer = (
            self._read_value(response, "answer")
            or self._read_value(response, "final_answer")
            or self._read_value(response, "response")
            or ""
        )
        if golden_query.must_contain_any:
            answer_lower = str(answer).lower()
            answer_contains_any: bool | None = any(term.lower() in answer_lower for term in golden_query.must_contain_any)
        else:
            answer_contains_any = None

        if retrieval_result is not None:
            retrieval_result.answer_contains_any = answer_contains_any
            if not retrieval_result.context_pack_id:
                retrieval_result.context_pack_id = self._read_str(response, "context_pack_id")
            if not retrieval_result.pipeline:
                retrieval_result.pipeline = self._read_dict(response, "pipeline")
            return retrieval_result

        return {
            "query_id": golden_query.query_id,
            "answer_contains_any": answer_contains_any,
            "context_pack_id": self._read_str(response, "context_pack_id"),
            "pipeline": self._read_dict(response, "pipeline"),
        }

    def summarize_results(self, results: list[RetrievalEvalResult]) -> dict[str, Any]:
        if not results:
            return {
                "total": 0,
                "error_count": 0,
                "avg_recall_expected_terms": 0.0,
                "avg_recall_expected_chunk_ids": 0.0,
                "avg_recall_expected_paper_ids": 0.0,
                "answer_contains_any_rate": None,
                "by_retrieval_mode": {},
            }

        by_mode: dict[str, list[RetrievalEvalResult]] = {}
        for result in results:
            by_mode.setdefault(result.retrieval_mode, []).append(result)

        answer_values = [result.answer_contains_any for result in results if result.answer_contains_any is not None]
        return {
            "total": len(results),
            "error_count": sum(1 for result in results if result.error),
            "avg_recall_expected_terms": self._average([result.recall_expected_terms for result in results]),
            "avg_recall_expected_chunk_ids": self._average([result.recall_expected_chunk_ids for result in results]),
            "avg_recall_expected_paper_ids": self._average([result.recall_expected_paper_ids for result in results]),
            "answer_contains_any_rate": self._bool_rate(answer_values),
            "by_retrieval_mode": {
                mode: {
                    "total": len(mode_results),
                    "error_count": sum(1 for result in mode_results if result.error),
                    "avg_recall_expected_terms": self._average([result.recall_expected_terms for result in mode_results]),
                    "avg_recall_expected_chunk_ids": self._average(
                        [result.recall_expected_chunk_ids for result in mode_results]
                    ),
                    "avg_recall_expected_paper_ids": self._average(
                        [result.recall_expected_paper_ids for result in mode_results]
                    ),
                    "answer_contains_any_rate": self._bool_rate(
                        [result.answer_contains_any for result in mode_results if result.answer_contains_any is not None]
                    ),
                }
                for mode, mode_results in by_mode.items()
            },
        }

    def to_jsonable(self, result: RetrievalEvalResult) -> dict[str, Any]:
        return asdict(result)

    def _extract_evidence(self, response: Any) -> list[Any]:
        for key in ("chunks", "evidence", "results", "items", "evidence_chunks"):
            value = self._read_value(response, key)
            if isinstance(value, list) and value:
                return value
        return []

    def _evidence_text(self, item: Any) -> str:
        return "\n".join(
            str(self._read_value(item, key) or "")
            for key in ("content", "content_preview", "text", "contextual_header", "section_title")
        )

    def _read_value(self, source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _read_str(self, source: Any, key: str) -> str | None:
        value = self._read_value(source, key)
        return str(value) if value is not None else None

    def _read_dict(self, source: Any, key: str) -> dict[str, Any]:
        value = self._read_value(source, key)
        return value if isinstance(value, dict) else {}

    def _string_value(self, source: Any, key: str) -> str | None:
        value = self._read_value(source, key)
        return str(value) if value is not None else None

    def _list_of_str(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _recall(self, matched: list[str], expected: list[str]) -> float:
        if not expected:
            return 1.0
        return len(matched) / len(expected)

    def _average(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _bool_rate(self, values: list[bool]) -> float | None:
        if not values:
            return None
        return sum(1 for value in values if value) / len(values)
