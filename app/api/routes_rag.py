from fastapi import APIRouter, HTTPException

from app.schemas.rag import (
    RagAnswerRequest,
    RagAnswerResponse,
    RagEvidenceEvaluationSummaryResponse,
    RagEvidenceFeedbackRequest,
    RagEvidenceFeedbackResponse,
    RagEvaluationSummaryResponse,
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
from app.services.rag_evaluation_service import RagEvaluationService
from app.services.rag_service import RagService

router = APIRouter(tags=["rag"])
rag_service = RagService()
rag_evaluation_service = RagEvaluationService()


@router.post("/index", response_model=RagIndexResponse)
def index_paper_for_rag(payload: RagIndexRequest) -> RagIndexResponse:
    return rag_service.index_paper_for_rag(
        paper_id=payload.paper_id,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )


@router.post("/search", response_model=RagSearchResponse)
def search_rag(payload: RagSearchRequest) -> RagSearchResponse:
    return rag_service.search_rag(
        query=payload.query,
        top_k=payload.top_k,
        paper_id=payload.paper_id,
    )


@router.post("/answer", response_model=RagAnswerResponse)
def answer_with_rag(payload: RagAnswerRequest) -> RagAnswerResponse:
    return rag_service.answer_with_rag(
        query=payload.query,
        top_k=payload.top_k,
        paper_id=payload.paper_id,
    )


@router.get("/traces/latest", response_model=RagTraceListResponse)
def get_latest_rag_traces(limit: int = 10) -> RagTraceListResponse:
    return RagTraceListResponse(success=True, items=rag_service.get_latest_traces(limit=limit))


@router.get("/traces/by-paper/{paper_id}", response_model=RagTraceListResponse)
def get_rag_traces_by_paper(paper_id: str, limit: int = 10) -> RagTraceListResponse:
    return RagTraceListResponse(success=True, items=rag_service.list_traces_by_paper(paper_id=paper_id, limit=limit))


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


@router.get("/evaluation/traces/{trace_id}/evidence", response_model=RagTraceEvidenceEvaluationResponse)
def get_rag_trace_evidence_evaluation(trace_id: str) -> dict:
    return rag_evaluation_service.get_trace_evidence_evaluation(trace_id)


@router.get("/evaluation/traces/{trace_id}", response_model=RagTraceEvaluationDetailResponse)
def get_rag_trace_evaluation_detail(trace_id: str) -> dict:
    return rag_evaluation_service.get_trace_evaluation_detail(trace_id)
