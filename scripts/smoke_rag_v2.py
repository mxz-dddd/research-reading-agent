"""本地 RAG v2 API smoke test；运行前请先启动 FastAPI 后端。"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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


def _fail(step: str, status: int | None, body: object) -> None:
    print(f"❌ {step} 失败")
    print(f"HTTP status: {status}")
    print(f"response/error: {_preview(body, 1000)}")
    sys.exit(1)


def _print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def _extract_context_pack_id(*responses: object) -> str | None:
    for response in responses:
        if not isinstance(response, dict):
            continue
        context_pack_id = response.get("context_pack_id")
        if context_pack_id:
            return str(context_pack_id)
        context_pack = response.get("context_pack")
        if isinstance(context_pack, dict):
            nested_id = context_pack.get("context_pack_id") or context_pack.get("id")
            if nested_id:
                return str(nested_id)
    return None


def _is_success(status: int) -> bool:
    return 200 <= status < 300


def _preview(value: object, max_len: int) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        text = str(value or "")
    return text[:max_len]


def _evidence_items(response: object) -> list[dict]:
    if not isinstance(response, dict):
        return []
    for key in ("chunks", "evidence", "results", "items", "evidence_chunks"):
        value = response.get(key)
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
    return []


def _print_pipeline(response: object) -> None:
    if not isinstance(response, dict):
        return
    pipeline = response.get("pipeline")
    if not isinstance(pipeline, dict) or not pipeline:
        return
    summary = {
        "retrieval_mode": pipeline.get("retrieval_mode"),
        "sparse_candidate_count": pipeline.get("sparse_candidate_count"),
        "dense_candidate_count": pipeline.get("dense_candidate_count"),
        "fused_candidate_count": pipeline.get("fused_candidate_count"),
        "rerank_enabled": pipeline.get("rerank_enabled"),
        "embedding_provider": pipeline.get("embedding_provider"),
        "rrf_k": pipeline.get("rrf_k"),
    }
    print("pipeline:", json.dumps(summary, ensure_ascii=False))


def _count_context_item_types(items: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(items, list):
        return counts
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("item_type")
        if item_type:
            counts[str(item_type)] = counts.get(str(item_type), 0) + 1
    return counts


def _build_payload(args: argparse.Namespace) -> dict:
    payload = {
        "query": args.query,
        "top_k": args.top_k,
        "user_id": args.user_id,
        "session_id": args.session_id,
        "retrieval_mode": args.retrieval_mode,
    }
    if args.paper_id:
        payload["paper_id"] = args.paper_id
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "RAG v2 API smoke test。\n\n"
            "示例命令：\n"
            ".venv/bin/python scripts/smoke_rag_v2.py \\\n"
            "  --base-url http://127.0.0.1:8000 \\\n"
            "  --paper-id 1 \\\n"
            "  --query \"这篇论文的方法和实验结论是什么？\" \\\n"
            "  --retrieval-mode hybrid"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--paper-id")
    parser.add_argument("--query", default="这篇论文的方法和实验结论是什么？")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--retrieval-mode", choices=["hybrid", "keyword"], default="hybrid")
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--session-id", default="smoke")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")

    _print_section("1. Health 检查")
    health_status, health_body, health_raw = _get_json(base_url, "/health")
    if not _is_success(health_status):
        _fail("health 检查", health_status, health_raw or health_body)
    print("✅ health 通过")
    print(_preview(health_body, 300))

    _print_section("2. RAG Index")
    if args.paper_id:
        index_payload = {
            "paper_id": args.paper_id,
            "index_version": "hybrid_v2",
            "chunker_version": "contextual_v1",
        }
        index_status, index_body, index_raw = _post_json(base_url, "/api/rag/index", index_payload)
        if not _is_success(index_status):
            _fail("RAG index", index_status, index_raw or index_body)
        print("✅ index 已执行")
        print(f"paper_id: {args.paper_id}")
        if isinstance(index_body, dict):
            print(
                "index_summary:",
                json.dumps(
                    {
                        "chunk_count": index_body.get("chunk_count"),
                        "chunks": index_body.get("chunks"),
                        "indexed_chunks": index_body.get("indexed_chunks"),
                    },
                    ensure_ascii=False,
                ),
            )
        else:
            print(_preview(index_body, 300))
    else:
        print("ℹ️ 未传 paper_id，跳过 index")

    request_payload = _build_payload(args)

    _print_section("3. RAG Search")
    search_status, search_body, search_raw = _post_json(base_url, "/api/rag/search", request_payload)
    if not _is_success(search_status):
        _fail("RAG search", search_status, search_raw or search_body)
    search_evidence_count = len(_evidence_items(search_body))
    search_context_pack_id = _extract_context_pack_id(search_body)
    print("✅ search 通过")
    print(f"evidence_count: {search_evidence_count}")
    print(f"context_pack_id: {search_context_pack_id or '-'}")
    _print_pipeline(search_body)

    _print_section("4. RAG Answer")
    answer_status, answer_body, answer_raw = _post_json(base_url, "/api/rag/answer", request_payload)
    if not _is_success(answer_status):
        _fail("RAG answer", answer_status, answer_raw or answer_body)
    answer_context_pack_id = _extract_context_pack_id(answer_body)
    print("✅ answer 通过")
    print(f"context_pack_id: {answer_context_pack_id or '-'}")
    if isinstance(answer_body, dict):
        answer = answer_body.get("answer") or answer_body.get("final_answer")
        if answer:
            print("answer_preview:", _preview(answer, 500))
    _print_pipeline(answer_body)

    _print_section("5. Context Pack 读取")
    context_pack_id = _extract_context_pack_id(search_body, answer_body)
    context_pack_loaded = False
    if context_pack_id:
        context_status, context_body, context_raw = _get_json(base_url, f"/api/rag/context-packs/{context_pack_id}")
        if not _is_success(context_status):
            _fail("Context Pack 读取", context_status, context_raw or context_body)
        context_pack_loaded = True
        print("✅ context_pack 可读取")
        if isinstance(context_body, dict):
            print(f"context_pack_id: {context_body.get('context_pack_id')}")
            print(f"item_count: {context_body.get('item_count')}")
            print(f"estimated_tokens: {context_body.get('estimated_tokens')}")
            print(f"token_budget: {context_body.get('token_budget')}")
            print("item_type_counts:", json.dumps(_count_context_item_types(context_body.get("items")), ensure_ascii=False))
        else:
            print(_preview(context_body, 300))
    else:
        print("⚠️ response 中没有 context_pack_id，跳过 context pack 读取")

    print("\n✅ RAG v2 smoke test 通过")
    print("summary:", json.dumps(
        {
            "base_url": base_url,
            "retrieval_mode": args.retrieval_mode,
            "paper_id": args.paper_id,
            "search_evidence_count": search_evidence_count,
            "answer_has_context_pack_id": bool(answer_context_pack_id),
            "context_pack_loaded": context_pack_loaded,
        },
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
