from pydantic import BaseModel, Field


class KnowledgeGenerateRequest(BaseModel):
    topic: str | None = Field(default=None, description="可选研究主题；为空则使用全部已接收论文")


class KnowledgeArtifactCreate(BaseModel):
    topic: str | None = None
    source_paper_count: int
    knowledge_tree_markdown: str
    learning_roadmap_markdown: str
    mermaid_mindmap: str
    mermaid_flowchart: str
    local_markdown_path: str
    generation_method: str


class KnowledgeArtifactRead(BaseModel):
    id: int
    topic: str | None = None
    source_paper_count: int
    knowledge_tree_markdown: str
    learning_roadmap_markdown: str
    mermaid_mindmap: str
    mermaid_flowchart: str
    local_markdown_path: str
    generation_method: str
    created_at: str
