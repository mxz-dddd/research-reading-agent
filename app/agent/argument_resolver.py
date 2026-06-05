from typing import Any

from app.agent.fallback_router import (
    extract_accept_top_k,
    extract_dry_run,
    extract_evidence_rank,
    extract_evidence_relevance_score,
    extract_max_results,
    extract_rag_chunk_id,
    extract_rag_query,
    extract_rag_feedback_notes,
    extract_rag_relevance_label,
    extract_rag_trace_id,
    extract_search_topic,
    extract_top_k,
    extract_workflow_topic,
    extract_workflow_index_rag,
)
from app.schemas.agent import AgentQueryRequest


def resolve_arguments(
    *,
    arguments: dict[str, Any],
    payload: AgentQueryRequest,
    tool_name: str,
    session_repo: Any,
) -> dict[str, Any]:
    if tool_name == "search_papers":
        arguments["topic"] = arguments.get("topic") or extract_search_topic(payload.text)
        arguments["max_results"] = int(arguments.get("max_results") or 5)
        arguments["topic_id"] = payload.topic_id
        arguments["user_id"] = payload.user_id
        arguments["session_id"] = payload.session_id
        return arguments

    if tool_name in {"accept_paper", "ingest_paper", "get_paper_detail"}:
        paper_id = arguments.get("paper_id")
        ordinal = arguments.get("ordinal")
        if paper_id is None and ordinal is not None:
            paper_id = session_repo.resolve_recent_position(
                payload.user_id,
                payload.session_id,
                int(ordinal),
            )
            if paper_id is None:
                raise ValueError(
                    f"我找不到最近搜索结果里的第 {ordinal} 篇。请先搜索论文，或直接提供 paper_id。"
                )
        if paper_id is None:
            raise ValueError("请提供 paper_id，或使用“第 N 篇”引用最近一次搜索结果。")
        return {"paper_id": int(paper_id)}

    if tool_name in {"generate_knowledge", "generate_innovation"}:
        return {"topic": arguments.get("topic")}

    if tool_name == "run_research_workflow":
        topic = arguments.get("topic") or extract_workflow_topic(payload.text)
        return {
            "topic": topic,
            "max_results": int(arguments.get("max_results") or extract_max_results(payload.text)),
            "accept_top_k": int(arguments.get("accept_top_k") or extract_accept_top_k(payload.text)),
            "ingest": bool(arguments.get("ingest", True)),
            "index_rag": _bool_value(arguments.get("index_rag"), default=True) or extract_workflow_index_rag(payload.text),
            "rag_chunk_size": int(arguments.get("rag_chunk_size") or 800),
            "rag_chunk_overlap": int(arguments.get("rag_chunk_overlap") or 120),
            "generate_knowledge": bool(arguments.get("generate_knowledge", True)),
            "generate_innovation": bool(arguments.get("generate_innovation", True)),
            "dry_run": _bool_value(arguments.get("dry_run"), default=False) or extract_dry_run(payload.text),
            "user_id": payload.user_id,
            "session_id": payload.session_id,
        }

    if tool_name == "list_workflow_history":
        return {"limit": int(arguments.get("limit") or 10)}

    if tool_name == "get_latest_workflow":
        return {}

    if tool_name == "get_workflow_detail":
        run_id = arguments.get("run_id")
        if not run_id:
            raise ValueError("请提供 workflow run_id。")
        return {"run_id": str(run_id)}

    if tool_name in {"generate_workflow_report", "get_workflow_report"}:
        run_id = arguments.get("run_id")
        return {"run_id": str(run_id) if run_id else None}

    if tool_name == "index_paper_rag":
        paper_id = _resolve_paper_id_argument(arguments, payload=payload, session_repo=session_repo)
        return {
            "paper_id": paper_id,
            "chunk_size": int(arguments.get("chunk_size") or 800),
            "chunk_overlap": int(arguments.get("chunk_overlap") or 120),
        }

    if tool_name in {"rag_search", "rag_answer"}:
        resolved: dict[str, Any] = {
            "query": arguments.get("query") or extract_rag_query(payload.text),
            "top_k": int(arguments.get("top_k") or extract_top_k(payload.text)),
        }
        paper_id = _resolve_optional_paper_id_argument(arguments, payload=payload, session_repo=session_repo)
        if paper_id is not None:
            resolved["paper_id"] = paper_id
        return resolved

    if tool_name == "get_latest_rag_traces":
        return {"limit": int(arguments.get("limit") or 10)}

    if tool_name == "get_rag_trace_detail":
        trace_id = arguments.get("trace_id") or extract_rag_trace_id(payload.text)
        if not trace_id:
            raise ValueError("请提供 RAG trace_id，例如 trace_xxx。")
        return {"trace_id": str(trace_id)}

    if tool_name == "get_rag_traces_by_paper":
        paper_id = _resolve_paper_id_argument(arguments, payload=payload, session_repo=session_repo)
        return {
            "paper_id": paper_id,
            "limit": int(arguments.get("limit") or 10),
        }

    if tool_name == "add_rag_trace_feedback":
        trace_id = arguments.get("trace_id") or extract_rag_trace_id(payload.text)
        if not trace_id:
            raise ValueError("请提供 RAG trace_id，例如 trace_xxx。")
        relevance_label = arguments.get("relevance_label") or extract_rag_relevance_label(payload.text)
        notes = arguments.get("notes") or extract_rag_feedback_notes(payload.text)
        expected_terms = arguments.get("expected_terms") or []
        return {
            "trace_id": str(trace_id),
            "relevance_label": str(relevance_label),
            "expected_terms": expected_terms,
            "notes": notes,
        }

    if tool_name == "get_rag_evaluation_summary":
        return {}

    if tool_name == "get_rag_trace_evaluation_detail":
        trace_id = arguments.get("trace_id") or extract_rag_trace_id(payload.text)
        if not trace_id:
            raise ValueError("请提供 RAG trace_id，例如 trace_xxx。")
        return {"trace_id": str(trace_id)}

    if tool_name == "add_rag_evidence_feedback":
        trace_id = arguments.get("trace_id") or extract_rag_trace_id(payload.text)
        if not trace_id:
            raise ValueError("请提供 RAG trace_id，例如 trace_xxx。")
        chunk_id = arguments.get("chunk_id") or extract_rag_chunk_id(payload.text)
        rank = arguments.get("rank")
        if rank is None:
            rank = extract_evidence_rank(payload.text)
        relevance_score = arguments.get("relevance_score")
        if relevance_score is None:
            relevance_score = extract_evidence_relevance_score(payload.text)
        notes = arguments.get("notes") or extract_rag_feedback_notes(payload.text)
        return {
            "trace_id": str(trace_id),
            "chunk_id": str(chunk_id) if chunk_id else None,
            "rank": int(rank) if rank is not None else None,
            "relevance_score": int(relevance_score),
            "notes": notes,
        }

    if tool_name == "get_rag_evidence_evaluation_summary":
        trace_id = arguments.get("trace_id") or extract_rag_trace_id(payload.text)
        return {"trace_id": str(trace_id) if trace_id else None}

    if tool_name == "get_rag_trace_evidence_evaluation":
        trace_id = arguments.get("trace_id") or extract_rag_trace_id(payload.text)
        if not trace_id:
            raise ValueError("请提供 RAG trace_id，例如 trace_xxx。")
        return {"trace_id": str(trace_id)}

    return arguments


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "是", "开启"}
    return bool(value)


def _resolve_paper_id_argument(
    arguments: dict[str, Any],
    *,
    payload: AgentQueryRequest,
    session_repo: Any,
) -> int:
    paper_id = _resolve_optional_paper_id_argument(arguments, payload=payload, session_repo=session_repo)
    if paper_id is None:
        raise ValueError("请提供 paper_id，或使用“第 N 篇”引用最近一次搜索结果。")
    return paper_id


def _resolve_optional_paper_id_argument(
    arguments: dict[str, Any],
    *,
    payload: AgentQueryRequest,
    session_repo: Any,
) -> int | None:
    paper_id = arguments.get("paper_id")
    ordinal = arguments.get("ordinal")
    if paper_id is None and ordinal is not None:
        paper_id = session_repo.resolve_recent_position(
            payload.user_id,
            payload.session_id,
            int(ordinal),
        )
        if paper_id is None:
            raise ValueError(
                f"我找不到最近搜索结果里的第 {ordinal} 篇。请先搜索论文，或直接提供 paper_id。"
            )
    if paper_id is None:
        return None
    return int(paper_id)
