from typing import Any

from pydantic import BaseModel, Field


class InnovationGenerateRequest(BaseModel):
    topic: str | None = Field(default=None, description="可选研究主题；为空则使用全部已接收论文")


class InnovationArtifactCreate(BaseModel):
    topic: str | None = None
    source_paper_count: int
    innovation_markdown: str
    innovation_json: dict[str, Any]
    summary_markdown: str
    generation_method: str
    local_markdown_path: str
    local_json_path: str


class InnovationArtifactRead(BaseModel):
    id: int
    topic: str | None = None
    source_paper_count: int
    innovation_markdown: str
    innovation_json: dict[str, Any]
    summary_markdown: str
    generation_method: str
    local_markdown_path: str
    local_json_path: str
    created_at: str
