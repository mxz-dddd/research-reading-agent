import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas.context import ContextItem, ContextPackRead
from app.schemas.rag import RagSearchChunk
from app.services.rag_debug_service import RagDebugService


def test_build_evidence_table_extracts_scores() -> None:
    service = RagDebugService()
    chunk = RagSearchChunk(
        chunk_id="chunk-1",
        paper_id="paper-1",
        chunk_index=3,
        section_title="Methods",
        score=1.7,
        content="Full evidence content.",
        content_preview="Evidence preview.",
        retrieval_scores={"sparse": 1.2, "dense": 0.8, "rrf": 0.03},
        rerank_score=2.5,
        score_reason="hybrid match",
    )

    rows = service.build_evidence_table([chunk])

    assert len(rows) == 1
    assert rows[0]["rank"] == 1
    assert rows[0]["sparse_score"] == 1.2
    assert rows[0]["dense_score"] == 0.8
    assert rows[0]["rrf_score"] == 0.03
    assert rows[0]["rerank_score"] == 2.5


def test_build_evidence_table_handles_missing_retrieval_scores() -> None:
    service = RagDebugService()
    chunk = RagSearchChunk(
        chunk_id="chunk-1",
        paper_id="paper-1",
        chunk_index=0,
        score=0.4,
        content="Full evidence content with\nextra whitespace.",
        content_preview="",
        retrieval_scores={},
    )

    rows = service.build_evidence_table([chunk])

    assert len(rows) == 1
    assert rows[0]["sparse_score"] == 0.0
    assert rows[0]["dense_score"] == 0.0
    assert rows[0]["rrf_score"] == 0.0
    assert rows[0]["content_preview"] == "Full evidence content with extra whitespace."


def test_build_context_summary_counts_item_types() -> None:
    service = RagDebugService()
    context_pack = ContextPackRead(
        context_pack_id="ctx-1",
        user_id="default",
        session_id="default",
        query="debug query",
        mode="answer",
        token_budget=6000,
        estimated_tokens=320,
        item_count=4,
        items=[
            ContextItem(item_type="rag_evidence", source_type="rag_chunk", content="evidence 1"),
            ContextItem(item_type="rag_evidence", source_type="rag_chunk", content="evidence 2"),
            ContextItem(item_type="active_paper", source_type="paper", content="paper"),
            ContextItem(
                item_type="session_recent_search_results",
                source_type="session_state",
                content="recent search",
            ),
        ],
    )

    summary = service.build_context_summary(context_pack)

    assert summary["context_pack_id"] == "ctx-1"
    assert summary["item_count"] == 4
    assert summary["estimated_tokens"] == 320
    assert summary["token_budget"] == 6000
    assert summary["item_type_counts"] == {
        "rag_evidence": 2,
        "active_paper": 1,
        "session_recent_search_results": 1,
    }


def test_build_context_summary_handles_none() -> None:
    summary = RagDebugService().build_context_summary(None)

    assert summary == {
        "context_pack_id": None,
        "item_count": 0,
        "estimated_tokens": 0,
        "token_budget": 0,
        "item_type_counts": {},
    }


def test_build_pipeline_summary_reads_plain_dict() -> None:
    pipeline = {
        "retrieval_mode": "hybrid",
        "sparse_candidate_count": 12,
        "dense_candidate_count": 10,
        "fused_candidate_count": 8,
        "rerank_enabled": True,
        "embedding_provider": "fake",
        "rrf_k": 60,
    }

    summary = RagDebugService().build_pipeline_summary(pipeline)

    assert summary == pipeline


def test_build_pipeline_summary_handles_none() -> None:
    summary = RagDebugService().build_pipeline_summary(None)

    assert summary == {
        "retrieval_mode": None,
        "sparse_candidate_count": 0,
        "dense_candidate_count": 0,
        "fused_candidate_count": 0,
        "rerank_enabled": False,
        "embedding_provider": None,
        "rrf_k": None,
    }
