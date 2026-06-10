from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PaperSearchRequest(BaseModel):
    topic_id: int | None = Field(default=None, description="已保存的研究方向 ID")
    topic: str | None = Field(default=None, min_length=1, description="搜索主题")
    max_results: int | None = Field(default=None, ge=1, le=20, description="返回论文数量")
    # 兼容第一阶段字段，后续可以逐步迁移到 topic / max_results。
    query: str | None = Field(default=None, min_length=1, description="搜索关键词或研究方向")
    limit: int | None = Field(default=None, ge=1, le=20, description="返回论文数量")

    @model_validator(mode="after")
    def require_topic_or_query(self) -> PaperSearchRequest:
        if not self.topic and not self.query:
            raise ValueError("topic 或 query 至少需要填写一个")
        return self

    @property
    def search_topic(self) -> str:
        return self.topic or self.query or ""

    @property
    def result_limit(self) -> int:
        return self.max_results or self.limit or 5


class PaperCreate(BaseModel):
    topic_id: int | None = None
    title: str
    authors: str | None = None
    abstract: str | None = None
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    summary: str | None = None
    screening_summary: str | None = None
    relevance_score: int | None = None
    worth_reading: str | None = None
    status: str = "found"


class PaperAcceptRequest(BaseModel):
    paper_id: int | None = Field(default=None, description="已入库论文 ID")
    url: str | None = Field(default=None, description="论文链接，paper_id 为空时使用")

    @model_validator(mode="after")
    def require_paper_id_or_url(self) -> PaperAcceptRequest:
        if self.paper_id is None and not self.url:
            raise ValueError("paper_id 或 url 至少需要填写一个")
        return self


class PaperIngestRequest(BaseModel):
    paper_id: int = Field(..., description="已确认论文 ID")


class PaperRead(BaseModel):
    id: int
    topic_id: int | None = None
    title: str
    authors: str | None = None
    abstract: str | None = None
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    summary: str | None = None
    screening_summary: str | None = None
    relevance_score: int | None = None
    worth_reading: str | None = None
    is_accepted: int = 0
    accepted_at: str | None = None
    pdf_url: str | None = None
    local_pdf_path: str | None = None
    local_text_path: str | None = None
    local_summary_path: str | None = None
    abstract_summary: str | None = None
    deep_summary: str | None = None
    ingest_status: str | None = None
    status: str
    created_at: str
    updated_at: str


class PaperSearchHistoryCreate(BaseModel):
    topic: str
    source: str
    result_count: int
    query_text: str


class PaperSearchHistoryRead(BaseModel):
    id: int
    topic: str
    source: str
    result_count: int
    query_text: str
    created_at: str
