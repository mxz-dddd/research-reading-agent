from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.repositories.session_repo import SessionStateRepository
from app.schemas.innovation import InnovationGenerateRequest
from app.schemas.knowledge import KnowledgeGenerateRequest
from app.schemas.paper import PaperAcceptRequest, PaperIngestRequest, PaperSearchRequest
from app.schemas.workflow import ResearchWorkflowRequest
from app.services.innovation_service import InnovationService
from app.services.knowledge_service import KnowledgeService
from app.services.paper_service import PaperService
from app.services.rag_evaluation_service import RagEvaluationService
from app.services.rag_service import RagService
from app.services.research_workflow_service import ResearchWorkflowService
from app.services.workflow_report_service import WorkflowReportService

# 工具的 LLM 面向参数 schema：单一事实源。
# 注意这是“给 LLM 看”的参数（例如包含 ordinal，由 argument_resolver 解析为 paper_id），
# 与实际 callable 签名可以不同，因此显式声明而非从函数签名反射。
TOOL_PARAMETER_SCHEMAS: dict[str, dict[str, str]] = {
    "search_papers": {
        "topic": "string",
        "max_results": "integer",
        "published_from": "string",
        "published_to": "string",
    },
    "accept_paper": {"paper_id": "integer", "ordinal": "integer"},
    "ingest_paper": {"paper_id": "integer", "ordinal": "integer"},
    "batch_ingest_papers": {"paper_ids": "array", "source_positions": "array"},
    "list_accepted_papers": {},
    "get_paper_detail": {"paper_id": "integer", "ordinal": "integer"},
    "generate_knowledge": {"topic": "string"},
    "generate_innovation": {"topic": "string"},
    "run_research_workflow": {
        "topic": "string",
        "max_results": "integer",
        "accept_top_k": "integer",
        "dry_run": "boolean",
        "index_rag": "boolean",
        "rag_chunk_size": "integer",
        "rag_chunk_overlap": "integer",
    },
    "get_latest_workflow": {},
    "list_workflow_history": {"limit": "integer"},
    "get_workflow_detail": {"run_id": "string"},
    "generate_workflow_report": {"run_id": "string"},
    "get_workflow_report": {"run_id": "string"},
    "index_paper_rag": {"paper_id": "integer", "ordinal": "integer"},
    "rag_search": {
        "query": "string",
        "top_k": "integer",
        "paper_id": "integer",
        "ordinal": "integer",
        "retrieval_mode": "string",
    },
    "rag_answer": {
        "query": "string",
        "top_k": "integer",
        "paper_id": "integer",
        "ordinal": "integer",
        "retrieval_mode": "string",
    },
    "get_latest_rag_traces": {"limit": "integer"},
    "get_rag_trace_detail": {"trace_id": "string"},
    "get_rag_traces_by_paper": {"paper_id": "integer", "ordinal": "integer", "limit": "integer"},
    "add_rag_trace_feedback": {
        "trace_id": "string",
        "relevance_label": "string",
        "expected_terms": "array",
        "notes": "string",
    },
    "get_rag_evaluation_summary": {},
    "get_rag_trace_evaluation_detail": {"trace_id": "string"},
    "add_rag_evidence_feedback": {
        "trace_id": "string",
        "chunk_id": "string",
        "rank": "integer",
        "relevance_score": "integer",
        "notes": "string",
    },
    "get_rag_evidence_evaluation_summary": {"trace_id": "string"},
    "get_rag_trace_evidence_evaluation": {"trace_id": "string"},
    "help": {},
}


def build_openai_tool_schema(name: str, properties: dict[str, str]) -> dict[str, Any]:
    """构造 Responses API 风格的 function tool 定义。"""
    return {
        "type": "function",
        "name": name,
        "description": f"调用 {name} 工具",
        "parameters": {
            "type": "object",
            "properties": {key: {"type": value} for key, value in properties.items()},
            "additionalProperties": False,
        },
    }


class ToolRegistry:
    def __init__(self) -> None:
        self.paper_service = PaperService()
        self.knowledge_service = KnowledgeService()
        self.innovation_service = InnovationService()
        self.rag_service = RagService()
        self.rag_evaluation_service = RagEvaluationService()
        self.workflow_service = ResearchWorkflowService()
        self.workflow_report_service = WorkflowReportService()
        self.session_repo = SessionStateRepository()
        self.tools: dict[str, Callable[..., Any]] = {
            "search_papers": self.search_papers,
            "accept_paper": self.accept_paper,
            "ingest_paper": self.ingest_paper,
            "batch_ingest_papers": self.batch_ingest_papers,
            "list_accepted_papers": self.list_accepted_papers,
            "get_paper_detail": self.get_paper_detail,
            "generate_knowledge": self.generate_knowledge,
            "generate_innovation": self.generate_innovation,
            "run_research_workflow": self.run_research_workflow,
            "get_latest_workflow": self.get_latest_workflow,
            "list_workflow_history": self.list_workflow_history,
            "get_workflow_detail": self.get_workflow_detail,
            "generate_workflow_report": self.generate_workflow_report,
            "get_workflow_report": self.get_workflow_report,
            "index_paper_rag": self.index_paper_rag,
            "rag_search": self.rag_search,
            "rag_answer": self.rag_answer,
            "get_latest_rag_traces": self.get_latest_rag_traces,
            "get_rag_trace_detail": self.get_rag_trace_detail,
            "get_rag_traces_by_paper": self.get_rag_traces_by_paper,
            "add_rag_trace_feedback": self.add_rag_trace_feedback,
            "get_rag_evaluation_summary": self.get_rag_evaluation_summary,
            "get_rag_trace_evaluation_detail": self.get_rag_trace_evaluation_detail,
            "add_rag_evidence_feedback": self.add_rag_evidence_feedback,
            "get_rag_evidence_evaluation_summary": self.get_rag_evidence_evaluation_summary,
            "get_rag_trace_evidence_evaluation": self.get_rag_trace_evidence_evaluation,
            "help": self.help,
        }

    def call(self, tool_name: str, **kwargs: Any) -> Any:
        if tool_name not in self.tools:
            raise ValueError(f"未知工具：{tool_name}")
        return self.tools[tool_name](**kwargs)

    def openai_tool_schemas(self) -> list[dict[str, Any]]:
        """从注册表派生 LLM 工具 schema，保证 schema 集合与已注册工具不漂移。"""
        missing = [name for name in self.tools if name not in TOOL_PARAMETER_SCHEMAS]
        if missing:
            raise ValueError(f"以下已注册工具缺少 LLM 参数 schema：{missing}")
        extra = [name for name in TOOL_PARAMETER_SCHEMAS if name not in self.tools]
        if extra:
            raise ValueError(f"以下参数 schema 对应的工具未注册：{extra}")
        return [build_openai_tool_schema(name, TOOL_PARAMETER_SCHEMAS[name]) for name in self.tools]

    def search_papers(
        self,
        *,
        topic: str,
        max_results: int = 5,
        published_from: str | None = None,
        published_to: str | None = None,
        exclude_urls: list[str] | None = None,
        exclude_paper_ids: list[int] | None = None,
        exclude_arxiv_ids: list[str] | None = None,
        append_mode: bool = False,
        result_offset: int = 0,
        topic_id: int | None = None,
        user_id: str = "default",
        session_id: str = "default",
    ) -> list[dict[str, Any]]:
        papers = self.paper_service.search_and_store(
            PaperSearchRequest(
                topic=topic,
                max_results=max_results,
                topic_id=topic_id,
                published_from=published_from,
                published_to=published_to,
                exclude_urls=exclude_urls or [],
                exclude_paper_ids=exclude_paper_ids or [],
                exclude_arxiv_ids=exclude_arxiv_ids or [],
                append_mode=append_mode,
            )
        )
        data = [paper.model_dump() for paper in papers]
        self.session_repo.save_recent_search_results(user_id, session_id, data)
        return data

    def accept_paper(self, *, paper_id: int) -> dict[str, Any]:
        return self.paper_service.accept_paper(PaperAcceptRequest(paper_id=paper_id)).model_dump()

    def ingest_paper(self, *, paper_id: int) -> dict[str, Any]:
        return self.paper_service.ingest_paper(PaperIngestRequest(paper_id=paper_id)).model_dump()

    def batch_ingest_papers(
        self,
        *,
        paper_ids: list[int],
        source_positions: list[int] | None = None,
    ) -> dict[str, Any]:
        positions = source_positions or list(range(1, len(paper_ids) + 1))
        items: list[dict[str, Any]] = []
        succeeded = 0
        for index, paper_id in enumerate(paper_ids):
            position = positions[index] if index < len(positions) else index + 1
            title: str | None = None
            try:
                title = self.paper_service.get_paper(int(paper_id)).title
                paper = self.paper_service.ingest_paper(PaperIngestRequest(paper_id=int(paper_id)))
                succeeded += 1
                items.append(
                    {
                        "position": int(position),
                        "paper_id": int(paper_id),
                        "title": paper.title,
                        "status": "success",
                        "ingest_status": paper.ingest_status,
                    }
                )
            except Exception as exc:
                error = exc.detail if isinstance(exc, HTTPException) else str(exc)
                items.append(
                    {
                        "position": int(position),
                        "paper_id": int(paper_id),
                        "title": title or f"论文 P{paper_id}",
                        "status": "failed",
                        "error": str(error)[:200] or type(exc).__name__,
                    }
                )
        return {
            "total": len(paper_ids),
            "succeeded": succeeded,
            "failed": len(paper_ids) - succeeded,
            "items": items,
        }

    def list_accepted_papers(self) -> list[dict[str, Any]]:
        return [paper.model_dump() for paper in self.paper_service.list_accepted()]

    def get_paper_detail(self, *, paper_id: int) -> dict[str, Any]:
        return self.paper_service.get_paper(paper_id).model_dump()

    def generate_knowledge(self, *, topic: str | None = None) -> dict[str, Any]:
        return self.knowledge_service.generate(KnowledgeGenerateRequest(topic=topic)).model_dump()

    def generate_innovation(self, *, topic: str | None = None) -> dict[str, Any]:
        return self.innovation_service.generate(InnovationGenerateRequest(topic=topic)).model_dump()

    def run_research_workflow(
        self,
        *,
        topic: str,
        max_results: int = 5,
        accept_top_k: int = 2,
        ingest: bool = True,
        index_rag: bool = True,
        rag_chunk_size: int = 800,
        rag_chunk_overlap: int = 120,
        generate_knowledge: bool = True,
        generate_innovation: bool = True,
        dry_run: bool = False,
        user_id: str = "default",
        session_id: str = "default",
    ) -> dict[str, Any]:
        result = self.workflow_service.run(
            ResearchWorkflowRequest(
                topic=topic,
                max_results=max_results,
                accept_top_k=accept_top_k,
                ingest=ingest,
                index_rag=index_rag,
                rag_chunk_size=rag_chunk_size,
                rag_chunk_overlap=rag_chunk_overlap,
                generate_knowledge=generate_knowledge,
                generate_innovation=generate_innovation,
                dry_run=dry_run,
                user_id=user_id,
                session_id=session_id,
            )
        )
        return result.model_dump()

    def get_latest_workflow(self) -> dict[str, Any]:
        run = self.workflow_service.latest_workflow()
        if run is None:
            return {"success": False, "message": "还没有 workflow run 记录", "data": None}
        return {"success": True, "data": run.model_dump()}

    def list_workflow_history(self, *, limit: int = 10) -> dict[str, Any]:
        runs = self.workflow_service.list_workflow_history(limit=limit)
        return {"success": True, "items": [run.model_dump() for run in runs]}

    def get_workflow_detail(self, *, run_id: str) -> dict[str, Any]:
        run = self.workflow_service.get_workflow_detail(run_id)
        return {"success": True, "data": run.model_dump()}

    def generate_workflow_report(self, *, run_id: str | None = None) -> dict[str, Any]:
        return self.workflow_report_service.generate_report(run_id).model_dump()

    def get_workflow_report(self, *, run_id: str | None = None) -> dict[str, Any]:
        return self.workflow_report_service.get_report(run_id).model_dump()

    def index_paper_rag(
        self,
        *,
        paper_id: int,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        index_version: str = "hybrid_v2",
        chunker_version: str = "contextual_v1",
    ) -> dict[str, Any]:
        return self.rag_service.index_paper_for_rag(
            paper_id=str(paper_id),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            index_version=index_version,
            chunker_version=chunker_version,
        ).model_dump()

    def rag_search(
        self,
        *,
        query: str,
        top_k: int = 5,
        paper_id: int | None = None,
        user_id: str = "default",
        session_id: str = "default",
        retrieval_mode: str | None = None,
    ) -> dict[str, Any]:
        return self.rag_service.search_rag(
            query=query,
            top_k=top_k,
            paper_id=str(paper_id) if paper_id is not None else None,
            user_id=user_id,
            session_id=session_id,
            retrieval_mode=retrieval_mode,
        ).model_dump()

    def rag_answer(
        self,
        *,
        query: str,
        top_k: int = 5,
        paper_id: int | None = None,
        user_id: str = "default",
        session_id: str = "default",
        retrieval_mode: str | None = None,
    ) -> dict[str, Any]:
        return self.rag_service.answer_with_rag(
            query=query,
            top_k=top_k,
            paper_id=str(paper_id) if paper_id is not None else None,
            user_id=user_id,
            session_id=session_id,
            retrieval_mode=retrieval_mode,
        ).model_dump()

    def get_latest_rag_traces(self, *, limit: int = 10) -> dict[str, Any]:
        traces = self.rag_service.get_latest_traces(limit=limit)
        return {"success": True, "items": [trace.model_dump() for trace in traces]}

    def get_rag_trace_detail(self, *, trace_id: str) -> dict[str, Any]:
        trace = self.rag_service.get_trace_detail(trace_id=trace_id)
        if trace is None:
            return {"success": False, "data": None, "message": "没有找到对应的 RAG trace。"}
        return {"success": True, "data": trace.model_dump()}

    def get_rag_traces_by_paper(self, *, paper_id: int, limit: int = 10) -> dict[str, Any]:
        traces = self.rag_service.list_traces_by_paper(paper_id=str(paper_id), limit=limit)
        return {"success": True, "items": [trace.model_dump() for trace in traces]}

    def add_rag_trace_feedback(
        self,
        *,
        trace_id: str,
        relevance_label: str,
        expected_terms: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        result = self.rag_evaluation_service.add_trace_feedback(
            trace_id=trace_id,
            relevance_label=relevance_label,
            expected_terms=expected_terms or [],
            notes=notes,
        )
        data = result.get("data")
        if data is not None:
            result["data"] = data.model_dump()
        return result

    def get_rag_evaluation_summary(self) -> dict[str, Any]:
        return self.rag_evaluation_service.get_rag_evaluation_summary()

    def get_rag_trace_evaluation_detail(self, *, trace_id: str) -> dict[str, Any]:
        result = self.rag_evaluation_service.get_trace_evaluation_detail(trace_id)
        trace = result.get("trace")
        feedback = result.get("latest_feedback")
        if trace is not None:
            result["trace"] = trace.model_dump()
        if feedback is not None:
            result["latest_feedback"] = feedback.model_dump()
        return result

    def add_rag_evidence_feedback(
        self,
        *,
        trace_id: str,
        chunk_id: str | None = None,
        rank: int | None = None,
        relevance_score: int,
        relevance_label: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        result = self.rag_evaluation_service.add_evidence_feedback(
            trace_id=trace_id,
            chunk_id=chunk_id,
            rank=rank,
            relevance_score=relevance_score,
            relevance_label=relevance_label,
            notes=notes,
        )
        data = result.get("data")
        if data is not None:
            result["data"] = data.model_dump()
        return result

    def get_rag_evidence_evaluation_summary(self, *, trace_id: str | None = None) -> dict[str, Any]:
        return self.rag_evaluation_service.get_evidence_evaluation_summary(trace_id=trace_id)

    def get_rag_trace_evidence_evaluation(self, *, trace_id: str) -> dict[str, Any]:
        return self.rag_evaluation_service.get_trace_evidence_evaluation(trace_id)

    def help(self) -> dict[str, Any]:
        return {
            "capabilities": [
                "搜索论文",
                "接收论文",
                "深入阅读并归档",
                "查看已接收论文",
                "查看单篇详情",
                "生成知识树和学习路径",
                "挖掘创新点",
                "一键运行完整研究闭环",
                "查看最近 workflow 结果和历史记录",
                "生成或查看 workflow 研究报告",
                "为已 ingest 论文建立轻量 RAG 索引并检索问答",
                "使用 contextual hybrid RAG 检索论文证据",
                "构造 Context Pack 记录回答使用的上下文",
                "查看 RAG evidence trace 记录",
                "为 RAG trace 添加人工相关性标注并查看评估摘要",
                "为单条 evidence chunk 添加相关性标注并查看 Recall@K / MRR / nDCG",
            ]
        }
