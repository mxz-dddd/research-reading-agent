from fastapi import APIRouter, HTTPException, Query

from app.repositories.context_repo import ContextPackRepository
from app.schemas.context import ContextPackRead
from app.schemas.rag import (
    RagAnswerRequest,
    RagAnswerResponse,
    RagEvaluationSummaryResponse,
    RagEvidenceEvaluationSummaryResponse,
    RagEvidenceFeedbackRequest,
    RagEvidenceFeedbackResponse,
    RagIndexRequest,
    RagIndexResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagTraceDetailResponse,
    RagTraceEvaluationDetailResponse,
    RagTraceEvidenceEvaluationResponse,
    RagTraceFeedbackRequest,
    RagTraceFeedbackResponse,
    RagTraceListResponse,
)
from app.services.rag_eval_run_service import RagEvalRunService
from app.services.rag_evaluation_service import RagEvaluationService
from app.services.rag_service import RagService

router = APIRouter(tags=["rag"])
rag_service = RagService()
rag_evaluation_service = RagEvaluationService()
rag_eval_run_service = RagEvalRunService()
context_repo = ContextPackRepository()


@router.post("/index", response_model=RagIndexResponse)
def index_paper_for_rag(payload: RagIndexRequest) -> RagIndexResponse:
    return rag_service.index_paper_for_rag(
        paper_id=payload.paper_id,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        index_version=payload.index_version,
        chunker_version=payload.chunker_version,
    )


@router.post("/search", response_model=RagSearchResponse)
def search_rag(payload: RagSearchRequest) -> RagSearchResponse:
    return rag_service.search_rag(
        query=payload.query,
        top_k=payload.top_k,
        paper_id=payload.paper_id,
        user_id=payload.user_id,
        session_id=payload.session_id,
        retrieval_mode=payload.retrieval_mode,
    )


@router.post("/answer", response_model=RagAnswerResponse)
def answer_with_rag(payload: RagAnswerRequest) -> RagAnswerResponse:
    return rag_service.answer_with_rag(
        query=payload.query,
        top_k=payload.top_k,
        paper_id=payload.paper_id,
        user_id=payload.user_id,
        session_id=payload.session_id,
        retrieval_mode=payload.retrieval_mode,
    )


@router.get("/context-packs/{context_pack_id}", response_model=ContextPackRead)
def get_context_pack(context_pack_id: str) -> ContextPackRead:
    context_pack = context_repo.get_context_pack(context_pack_id)
    if context_pack is None:
        raise HTTPException(status_code=404, detail="context_pack_id not found")
    return context_pack


@router.get("/context-packs")
def list_context_packs(
    user_id: str = "default",
    session_id: str = "default",
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    items = context_repo.list_latest(user_id=user_id, session_id=session_id, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/eval-runs")
def list_rag_eval_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    items = rag_eval_run_service.list_runs(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/eval-runs/{run_id}")
def get_rag_eval_run(run_id: str) -> dict:
    run = rag_eval_run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    return run


@router.get("/traces/latest", response_model=RagTraceListResponse)
def get_latest_rag_traces(limit: int = 10) -> RagTraceListResponse:
    return RagTraceListResponse(success=True, items=rag_service.get_latest_traces(limit=limit))


@router.get("/traces/by-paper/{paper_id}", response_model=RagTraceListResponse)
def get_rag_traces_by_paper(paper_id: str, limit: int = 10) -> RagTraceListResponse:
    return RagTraceListResponse(
        success=True, items=rag_service.list_traces_by_paper(paper_id=paper_id, limit=limit)
    )


@router.post("/traces/{trace_id}/feedback", response_model=RagTraceFeedbackResponse)
def add_rag_trace_feedback(trace_id: str, payload: RagTraceFeedbackRequest) -> dict:
    return rag_evaluation_service.add_trace_feedback(
        trace_id=trace_id,
        relevance_label=payload.relevance_label,
        expected_terms=payload.expected_terms,
        notes=payload.notes,
    )


@router.post("/traces/{trace_id}/evidence-feedback", response_model=RagEvidenceFeedbackResponse)
def add_rag_evidence_feedback(trace_id: str, payload: RagEvidenceFeedbackRequest) -> dict:
    return rag_evaluation_service.add_evidence_feedback(
        trace_id=trace_id,
        chunk_id=payload.chunk_id,
        rank=payload.rank,
        relevance_score=payload.relevance_score,
        relevance_label=payload.relevance_label,
        notes=payload.notes,
    )


@router.get("/traces/{trace_id}", response_model=RagTraceDetailResponse)
def get_rag_trace_detail(trace_id: str) -> RagTraceDetailResponse:
    trace = rag_service.get_trace_detail(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="RAG trace not found")
    return RagTraceDetailResponse(success=True, data=trace)


@router.get("/evaluation/summary", response_model=RagEvaluationSummaryResponse)
def get_rag_evaluation_summary() -> dict:
    return rag_evaluation_service.get_rag_evaluation_summary()


@router.get("/evaluation/evidence-summary", response_model=RagEvidenceEvaluationSummaryResponse)
def get_rag_evidence_evaluation_summary(trace_id: str | None = None) -> dict:
    return rag_evaluation_service.get_evidence_evaluation_summary(trace_id=trace_id)


@router.get(
    "/evaluation/traces/{trace_id}/evidence", response_model=RagTraceEvidenceEvaluationResponse
)
def get_rag_trace_evidence_evaluation(trace_id: str) -> dict:
    return rag_evaluation_service.get_trace_evidence_evaluation(trace_id)


@router.get("/evaluation/traces/{trace_id}", response_model=RagTraceEvaluationDetailResponse)
def get_rag_trace_evaluation_detail(trace_id: str) -> dict:
    return rag_evaluation_service.get_trace_evaluation_detail(trace_id)
