from __future__ import annotations

from pydantic import BaseModel, Field


class TopicCreate(BaseModel):
    title: str = Field(..., min_length=1, description="研究方向标题")
    description: str | None = Field(default=None, description="研究方向补充说明")


class TopicRead(BaseModel):
    id: int
    title: str
    description: str | None = None
    created_at: str
    updated_at: str
