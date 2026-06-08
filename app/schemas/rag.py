from typing import Any

from pydantic import BaseModel, Field


class RagIndexRequest(BaseModel):
    paper_id: str = Field(..., description="论文 ID")
    chunk_size: int = Field(default=800, ge=100, le=4000, description="chunk 字符数")
    chunk_overlap: int = Field(default=120, ge=0, le=1000, description="相邻 chunk 重叠字符数")
    index_version: str = "hybrid_v2"
    chunker_version: str = "contextual_v1"


class RagSearchRequest(BaseModel):
    query: str = Field(..., description="检索问题或关键词")
    top_k: int = Field(default=5, ge=1, le=20, description="返回 evidence chunk 数量")
    paper_id: str | None = Field(default=None, description="可选论文 ID")
    user_id: str = "default"
    session_id: str = "default"
    retrieval_mode: str | None = None


class RagAnswerRequest(BaseModel):
    query: str = Field(..., description="问答问题")
    top_k: int = Field(default=5, ge=1, le=20, description="用于回答的 evidence chunk 数量")
    paper_id: str | None = Field(default=None, description="可选论文 ID")
    user_id: str = "default"
    session_id: str = "default"
    retrieval_mode: str | None = None


class RagChunkCreate(BaseModel):
    chunk_id: str
    paper_id: str
    source_type: str
    source_path: str | None = None
    chunk_index: int
    content: str
    content_preview: str
    metadata: dict[str, Any] = {}
    contextual_header: str | None = None
    section_title: str | None = None
    content_for_embedding: str | None = None
    token_count: int = 0
    chunker_version: str = "contextual_v1"
    index_version: str = "hybrid_v2"


class RagChunkRead(BaseModel):
    id: int
    chunk_id: str
    paper_id: str
    source_type: str
    source_path: str | None = None
    chunk_index: int
    content: str
    content_preview: str
    metadata: dict[str, Any] = {}
    contextual_header: str | None = None
    section_title: str | None = None
    content_for_embedding: str | None = None
    token_count: int = 0
    chunker_version: str = "contextual_v1"
    index_version: str = "hybrid_v2"
    created_at: str


class RagSearchChunk(BaseModel):
    score: float
    chunk_id: str
    paper_id: str
    chunk_index: int | None = None
    matched_terms: list[str] = []
    content: str
    content_preview: str
    source_path: str | None = None
    metadata: dict[str, Any] = {}
    score_reason: str | None = None
    retrieval_scores: dict[str, float] = {}
    rerank_score: float | None = None
    section_title: str | None = None
    contextual_header: str | None = None


class RagIndexResponse(BaseModel):
    success: bool
    paper_id: str
    chunk_count: int = 0
    warnings: list[str] = []
    error: str | None = None


class RagSearchResponse(BaseModel):
    success: bool
    query: str
    evidence_chunks: list[RagSearchChunk] = []
    message: str | None = None
    no_evidence: bool = False
    error: str | None = None
    trace_id: str | None = None
    trace_warning: str | None = None
    retrieval_mode: str | None = None
    context_pack_id: str | None = None
    context_pack: dict[str, Any] | None = None
    pipeline: dict[str, Any] = {}


class RagAnswerResponse(BaseModel):
    success: bool
    query: str
    answer: str
    evidence_chunks: list[RagSearchChunk] = []
    warning: str | None = None
    no_evidence: bool = False
    error: str | None = None
    trace_id: str | None = None
    trace_warning: str | None = None
    retrieval_mode: str | None = None
    context_pack_id: str | None = None
    context_pack: dict[str, Any] | None = None
    pipeline: dict[str, Any] = {}


class RagTraceCreate(BaseModel):
    trace_id: str
    query: str
    mode: str
    paper_id: str | None = None
    top_k: int
    hit_count: int
    no_evidence: bool
    answer: str | None = None
    evidence: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}


class RagTraceRead(BaseModel):
    id: int
    trace_id: str
    query: str
    mode: str
    paper_id: str | None = None
    top_k: int
    hit_count: int
    no_evidence: bool
    answer: str | None = None
    evidence: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    created_at: str


class RagTraceListResponse(BaseModel):
    success: bool
    items: list[RagTraceRead] = []


class RagTraceDetailResponse(BaseModel):
    success: bool
    data: RagTraceRead | None = None
    message: str | None = None


class RagTraceFeedbackRequest(BaseModel):
    relevance_label: str = Field(..., description="相关性标注")
    expected_terms: list[str] = []
    notes: str | None = None


class RagTraceFeedbackRead(BaseModel):
    id: int
    feedback_id: str
    trace_id: str
    relevance_label: str
    expected_terms: list[str] = []
    notes: str | None = None
    created_at: str


class RagTraceFeedbackResponse(BaseModel):
    success: bool
    data: RagTraceFeedbackRead | None = None
    message: str | None = None
    error: str | None = None


class RagEvaluationSummaryResponse(BaseModel):
    success: bool
    summary: dict[str, Any]


class RagTraceEvaluationDetailResponse(BaseModel):
    success: bool
    trace: RagTraceRead | None = None
    latest_feedback: RagTraceFeedbackRead | None = None
    message: str | None = None
    error: str | None = None


class RagEvidenceFeedbackRequest(BaseModel):
    chunk_id: str | None = None
    rank: int | None = None
    relevance_score: int = Field(..., ge=0, le=2)
    relevance_label: str | None = None
    notes: str | None = None


class RagEvidenceFeedbackRead(BaseModel):
    id: int
    evidence_feedback_id: str
    trace_id: str
    chunk_id: str
    rank: int
    relevance_score: int
    relevance_label: str
    notes: str | None = None
    created_at: str


class RagEvidenceFeedbackResponse(BaseModel):
    success: bool
    data: RagEvidenceFeedbackRead | None = None
    message: str | None = None
    error: str | None = None


class RagEvidenceEvaluationSummaryResponse(BaseModel):
    success: bool
    summary: dict[str, Any]
    message: str | None = None


class RagTraceEvidenceEvaluationResponse(BaseModel):
    success: bool
    trace_id: str
    evidence: list[dict[str, Any]] = []
    message: str | None = None
    error: str | None = None
