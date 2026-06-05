from typing import Any

from pydantic import BaseModel, Field, model_validator


class AgentQueryRequest(BaseModel):
    user_id: str = Field(default="default", description="用户 ID，第一阶段可传默认值")
    session_id: str = Field(default="default", description="会话 ID，用于保存最近搜索结果")
    message: str | None = Field(default=None, min_length=1, description="用户自然语言请求")
    # 兼容第一阶段字段。
    query: str | None = Field(default=None, min_length=1, description="用户自然语言请求")
    topic_id: int | None = Field(default=None, description="可选研究方向 ID")

    @model_validator(mode="after")
    def require_message_or_query(self) -> "AgentQueryRequest":
        if not self.message and not self.query:
            raise ValueError("message 或 query 至少需要填写一个")
        return self

    @property
    def text(self) -> str:
        return (self.message or self.query or "").strip()


class AgentToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    success: bool
    error: str | None = None


class AgentQueryResponse(BaseModel):
    success: bool
    intent: str
    chosen_tool: str | None = None
    tool_calls: list[AgentToolCall] = []
    final_answer: str
    data: Any = None
    error: str | None = None
    routing_method: str = "fallback"
    # 兼容旧字段，方便已有调用方逐步迁移。
    answer: str | None = None
    used_tool: str | None = None
