from typing import Any

from pydantic import BaseModel, Field


class ResearchWorkflowRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="研究方向或论文搜索主题")
    max_results: int = Field(default=5, ge=1, le=20, description="论文搜索数量")
    accept_top_k: int = Field(default=2, ge=1, le=20, description="自动接收前 K 篇论文")
    ingest: bool = Field(default=True, description="是否对已接收论文执行深入阅读")
    index_rag: bool = Field(default=True, description="是否在 ingest 后为论文建立 RAG v1 索引")
    rag_chunk_size: int = Field(default=800, ge=100, le=4000, description="RAG chunk 字符数")
    rag_chunk_overlap: int = Field(default=120, ge=0, le=1000, description="RAG chunk 重叠字符数")
    generate_knowledge: bool = Field(default=True, description="是否生成知识树")
    generate_innovation: bool = Field(default=True, description="是否生成创新点分析")
    dry_run: bool = Field(
        default=False, description="是否使用模拟数据演示完整 workflow，不访问外部服务或数据库"
    )
    user_id: str = Field(default="default", description="用户 ID，用于 Agent 会话兼容")
    session_id: str = Field(default="default", description="会话 ID，用于 Agent 会话兼容")


class ResearchWorkflowStep(BaseModel):
    step: str
    success: bool
    summary: str
    data: Any = None
    error: str | None = None


class ResearchWorkflowResponse(BaseModel):
    run_id: str | None = None
    success: bool
    topic: str
    dry_run: bool = False
    steps: list[ResearchWorkflowStep]
    searched_papers: list[dict[str, Any]]
    accepted_papers: list[dict[str, Any]]
    ingested_papers: list[dict[str, Any]]
    rag_indexed_papers: list[dict[str, Any]] = []
    knowledge: dict[str, Any] | None = None
    innovation: dict[str, Any] | None = None
    warnings: list[str] = []
    error: str | None = None


class WorkflowRunCreate(BaseModel):
    run_id: str
    topic: str
    success: bool
    dry_run: bool = False
    max_results: int
    accept_top_k: int
    searched_count: int
    accepted_count: int
    ingested_count: int
    knowledge_generated: bool
    innovation_generated: bool
    warnings: list[str] = []
    result: dict[str, Any]
    error: str | None = None


class WorkflowRunSummary(BaseModel):
    id: int
    run_id: str
    topic: str
    success: bool
    dry_run: bool = False
    max_results: int
    accept_top_k: int
    searched_count: int
    accepted_count: int
    ingested_count: int
    knowledge_generated: bool
    innovation_generated: bool
    warnings: list[str] = []
    error: str | None = None
    created_at: str


class WorkflowRunDetail(WorkflowRunSummary):
    result: dict[str, Any]


class WorkflowRunLatestResponse(BaseModel):
    success: bool
    data: WorkflowRunDetail | None = None
    message: str | None = None


class WorkflowRunHistoryResponse(BaseModel):
    success: bool
    items: list[WorkflowRunSummary]


class WorkflowRunDetailResponse(BaseModel):
    success: bool
    data: WorkflowRunDetail


class WorkflowReportResponse(BaseModel):
    success: bool
    run_id: str | None = None
    report_path: str | None = None
    report_markdown: str | None = None
    error: str | None = None
