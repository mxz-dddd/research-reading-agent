"""本地 RAG v2 golden queries 评估脚本；运行前请先启动 FastAPI 后端。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from app.services.rag_quality_eval_service import GoldenQuery, RetrievalEvalResult
else:
    _rag_quality_module = import_module("app.services.rag_quality_eval_service")
    GoldenQuery = _rag_quality_module.GoldenQuery
    RetrievalEvalResult = _rag_quality_module.RetrievalEvalResult
RagQualityEvalService = import_module("app.services.rag_quality_eval_service").RagQualityEvalService


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    timeout: int = 20,
) -> tuple[int, dict | list | str | None, str]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            text = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")[:1000]
        return exc.code, None, text
    except (URLError, TimeoutError) as exc:
        return 0, None, str(exc)[:1000]
    except Exception as exc:
        return 0, None, str(exc)[:1000]

    if not text:
        return status, None, ""
    try:
        return status, json.loads(text), text
    except json.JSONDecodeError:
        return status, text, text


def _get_json(base_url: str, path: str) -> tuple[int, object, str]:
    return _request_json("GET", _join_url(base_url, path))


def _post_json(base_url: str, path: str, payload: dict) -> tuple[int, object, str]:
    return _request_json("POST", _join_url(base_url, path), payload=payload)


def _is_success(status: int) -> bool:
    return 200 <= status < 300


def _parse_retrieval_modes(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_payload(
    golden_query: GoldenQuery,
    *,
    retrieval_mode: str,
    top_k: int,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": golden_query.query,
        "top_k": top_k,
        "user_id": user_id,
        "session_id": session_id,
        "retrieval_mode": retrieval_mode,
    }
    if golden_query.paper_id:
        payload["paper_id"] = golden_query.paper_id
    return payload


def _error_result(
    golden_query: GoldenQuery,
    *,
    retrieval_mode: str,
    top_k: int,
    error: str,
) -> RetrievalEvalResult:
    return RetrievalEvalResult(
        query_id=golden_query.query_id,
        query=golden_query.query,
        retrieval_mode=retrieval_mode,
        top_k=top_k,
        evidence_count=0,
        matched_expected_terms=[],
        missing_expected_terms=golden_query.expected_terms,
        matched_expected_chunk_ids=[],
        missing_expected_chunk_ids=golden_query.expected_chunk_ids,
        matched_expected_paper_ids=[],
        missing_expected_paper_ids=golden_query.expected_paper_ids,
        recall_expected_terms=0.0 if golden_query.expected_terms else 1.0,
        recall_expected_chunk_ids=0.0 if golden_query.expected_chunk_ids else 1.0,
        recall_expected_paper_ids=0.0 if golden_query.expected_paper_ids else 1.0,
        answer_contains_any=None,
        context_pack_id=None,
        pipeline={},
        error=error,
    )


def _default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("eval") / "rag_eval_runs" / f"rag_eval_{timestamp}.json"


def _save_json(path: str | Path, payload: dict[str, Any]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def run_eval(args: argparse.Namespace) -> tuple[int, dict[str, Any] | None]:
    base_url = args.base_url.rstrip("/")
    health_status, health_body, health_raw = _get_json(base_url, "/health")
    if not _is_success(health_status):
        print("❌ /health 检查失败")
        print(f"HTTP status: {health_status}")
        print(str(health_raw or health_body)[:1000])
        return 1, None

    service = RagQualityEvalService()
    try:
        golden_queries = service.load_golden_queries(args.golden_file)
    except ValueError as exc:
        print(f"❌ golden queries 读取失败：{exc}")
        return 1, None

    retrieval_modes = _parse_retrieval_modes(args.retrieval_modes)
    results: list[RetrievalEvalResult] = []

    for golden_query in golden_queries:
        for mode in retrieval_modes:
            payload = _build_payload(
                golden_query,
                retrieval_mode=mode,
                top_k=args.top_k,
                user_id=args.user_id,
                session_id=args.session_id,
            )
            status, body, raw = _post_json(base_url, "/api/rag/search", payload)
            if not _is_success(status):
                results.append(
                    _error_result(
                        golden_query,
                        retrieval_mode=mode,
                        top_k=args.top_k,
                        error=f"search HTTP {status}: {str(raw or body)[:1000]}",
                    )
                )
                continue

            result = service.evaluate_search_response(
                golden_query,
                body,
                retrieval_mode=mode,
                top_k=args.top_k,
            )

            if args.run_answer:
                answer_status, answer_body, answer_raw = _post_json(
                    base_url, "/api/rag/answer", payload
                )
                if _is_success(answer_status):
                    service.evaluate_answer_response(golden_query, answer_body, result)
                else:
                    result.error = (
                        f"answer HTTP {answer_status}: {str(answer_raw or answer_body)[:1000]}"
                    )

            results.append(result)

    summary = service.summarize_results(results)
    output = {
        "created_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "golden_file": str(args.golden_file),
        "retrieval_modes": retrieval_modes,
        "top_k": args.top_k,
        "run_answer": args.run_answer,
        "summary": summary,
        "results": [service.to_jsonable(result) for result in results],
    }
    output_path = _save_json(args.output or _default_output_path(), output)

    print("✅ RAG v2 golden queries 评估完成")
    print(f"golden query 数量: {len(golden_queries)}")
    print(f"retrieval modes: {', '.join(retrieval_modes)}")
    print(f"total eval cases: {summary['total']}")
    print(f"avg_recall_expected_terms: {summary['avg_recall_expected_terms']:.3f}")
    print(f"avg_recall_expected_chunk_ids: {summary['avg_recall_expected_chunk_ids']:.3f}")
    print(f"avg_recall_expected_paper_ids: {summary['avg_recall_expected_paper_ids']:.3f}")
    print(f"answer_contains_any_rate: {summary['answer_contains_any_rate']}")
    print(f"llm_answer_rate: {summary.get('llm_answer_rate')}")
    print(f"citation_faithful_rate: {summary.get('citation_faithful_rate')}")
    print(f"avg_citation_precision: {summary.get('avg_citation_precision')}")
    print(f"error_count: {summary['error_count']}")
    print(f"输出文件路径: {output_path}")
    return 0, output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地 RAG v2 golden queries 质量评估。")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--golden-file", default="eval/golden_queries.example.jsonl")
    parser.add_argument("--retrieval-modes", default="hybrid,keyword")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--session-id", default="eval")
    parser.add_argument("--run-answer", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def main() -> None:
    exit_code, _ = run_eval(parse_args())
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
