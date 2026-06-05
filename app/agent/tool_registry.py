from typing import Any, Callable

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

    def search_papers(
        self,
        *,
        topic: str,
        max_results: int = 5,
        topic_id: int | None = None,
        user_id: str = "default",
        session_id: str = "default",
    ) -> list[dict[str, Any]]:
        papers = self.paper_service.search_and_store(
            PaperSearchRequest(topic=topic, max_results=max_results, topic_id=topic_id)
        )
        data = [paper.model_dump() for paper in papers]
        self.session_repo.save_recent_search_results(user_id, session_id, data)
        return data

    def accept_paper(self, *, paper_id: int) -> dict[str, Any]:
        return self.paper_service.accept_paper(PaperAcceptRequest(paper_id=paper_id)).model_dump()

    def ingest_paper(self, *, paper_id: int) -> dict[str, Any]:
        return self.paper_service.ingest_paper(PaperIngestRequest(paper_id=paper_id)).model_dump()

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
    ) -> dict[str, Any]:
        return self.rag_service.index_paper_for_rag(
            paper_id=str(paper_id),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ).model_dump()

    def rag_search(
        self,
        *,
        query: str,
        top_k: int = 5,
        paper_id: int | None = None,
    ) -> dict[str, Any]:
        return self.rag_service.search_rag(
            query=query,
            top_k=top_k,
            paper_id=str(paper_id) if paper_id is not None else None,
        ).model_dump()

    def rag_answer(
        self,
        *,
        query: str,
        top_k: int = 5,
        paper_id: int | None = None,
    ) -> dict[str, Any]:
        return self.rag_service.answer_with_rag(
            query=query,
            top_k=top_k,
            paper_id=str(paper_id) if paper_id is not None else None,
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
                "查看 RAG evidence trace 记录",
                "为 RAG trace 添加人工相关性标注并查看评估摘要",
                "为单条 evidence chunk 添加相关性标注并查看 Recall@K / MRR / nDCG",
            ]
        }
