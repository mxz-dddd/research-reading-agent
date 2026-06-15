from typing import Any
from uuid import uuid4

from app.repositories.workflow_repo import WorkflowRunRepository
from app.schemas.innovation import InnovationGenerateRequest
from app.schemas.knowledge import KnowledgeGenerateRequest
from app.schemas.paper import PaperAcceptRequest, PaperIngestRequest, PaperRead, PaperSearchRequest
from app.schemas.workflow import (
    ResearchWorkflowRequest,
    ResearchWorkflowResponse,
    ResearchWorkflowStep,
    WorkflowRunCreate,
    WorkflowRunDetail,
    WorkflowRunSummary,
)
from app.services.innovation_service import InnovationService
from app.services.knowledge_service import KnowledgeService
from app.services.paper_service import PaperService
from app.services.rag_service import RagService


class ResearchWorkflowService:
    def __init__(self) -> None:
        self.paper_service = PaperService()
        self.knowledge_service = KnowledgeService()
        self.innovation_service = InnovationService()
        self.rag_service = RagService()
        self.workflow_repo = WorkflowRunRepository()

    def run(self, payload: ResearchWorkflowRequest) -> ResearchWorkflowResponse:
        return self.run_research_workflow(
            topic=payload.topic,
            max_results=payload.max_results,
            accept_top_k=payload.accept_top_k,
            ingest=payload.ingest,
            index_rag=payload.index_rag,
            rag_chunk_size=payload.rag_chunk_size,
            rag_chunk_overlap=payload.rag_chunk_overlap,
            generate_knowledge=payload.generate_knowledge,
            generate_innovation=payload.generate_innovation,
            dry_run=payload.dry_run,
            user_id=payload.user_id,
            session_id=payload.session_id,
        )

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
    ) -> ResearchWorkflowResponse:
        topic = topic.strip()
        run_id = uuid4().hex
        if dry_run:
            response = self._run_dry_run_workflow(
                run_id=run_id,
                topic=topic,
                max_results=max_results,
                accept_top_k=accept_top_k,
                ingest=ingest,
                index_rag=index_rag,
                rag_chunk_size=rag_chunk_size,
                rag_chunk_overlap=rag_chunk_overlap,
                generate_knowledge=generate_knowledge,
                generate_innovation=generate_innovation,
            )
            return self._persist_response(response, max_results=max_results, accept_top_k=accept_top_k)

        steps: list[ResearchWorkflowStep] = []
        warnings: list[str] = []
        searched_papers: list[dict[str, Any]] = []
        accepted_papers: list[dict[str, Any]] = []
        ingested_papers: list[dict[str, Any]] = []
        rag_indexed_papers: list[dict[str, Any]] = []
        knowledge: dict[str, Any] | None = None
        innovation: dict[str, Any] | None = None

        def finalize(*, success: bool, error: str | None) -> ResearchWorkflowResponse:
            # 统一从累积的局部状态构造并持久化响应，避免每个提前返回重复一长串字段。
            response = self._response(
                run_id=run_id,
                success=success,
                topic=topic,
                steps=steps,
                searched_papers=searched_papers,
                accepted_papers=accepted_papers,
                ingested_papers=ingested_papers,
                rag_indexed_papers=rag_indexed_papers,
                knowledge=knowledge,
                innovation=innovation,
                warnings=warnings,
                error=error,
            )
            return self._persist_response(
                response, max_results=max_results, accept_top_k=accept_top_k
            )

        try:
            papers = self.paper_service.search_and_store(
                PaperSearchRequest(topic=topic, max_results=max_results)
            )
        except Exception as exc:
            error = f"论文搜索失败：{exc}"
            steps.append(self._step("search_papers", False, error, error=error))
            return finalize(success=False, error=error)

        searched_papers = [self._paper_summary(paper) for paper in papers]
        steps.append(
            self._step(
                "search_papers",
                True,
                f"已搜索到 {len(searched_papers)} 篇候选论文。",
                data={"count": len(searched_papers), "papers": searched_papers},
            )
        )
        if not papers:
            error = "没有搜索到候选论文，workflow 已停止。"
            warnings.append(error)
            return finalize(success=False, error=error)

        accept_errors: list[dict[str, Any]] = []
        for paper in papers[:accept_top_k]:
            try:
                accepted = self.paper_service.accept_paper(PaperAcceptRequest(paper_id=paper.id))
                accepted_papers.append(self._paper_summary(accepted))
            except Exception as exc:
                message = f"接收论文 P{paper.id} 失败：{exc}"
                warnings.append(message)
                accept_errors.append({"paper_id": paper.id, "error": str(exc)})

        steps.append(
            self._step(
                "accept_top_k",
                bool(accepted_papers),
                f"已接收 {len(accepted_papers)} / {min(accept_top_k, len(papers))} 篇论文。",
                data={"papers": accepted_papers, "errors": accept_errors},
                error=None if accepted_papers else "没有论文成功接收。",
            )
        )
        if not accepted_papers:
            error = "没有论文成功接收，workflow 已停止。"
            return finalize(success=False, error=error)

        if ingest:
            ingest_errors: list[dict[str, Any]] = []
            for paper in accepted_papers:
                paper_id = int(paper["id"])
                try:
                    ingested = self.paper_service.ingest_paper(PaperIngestRequest(paper_id=paper_id))
                    ingested_papers.append(self._paper_summary(ingested))
                except Exception as exc:
                    message = f"深入阅读论文 P{paper_id} 失败：{exc}"
                    warnings.append(message)
                    ingest_errors.append({"paper_id": paper_id, "error": str(exc)})

            steps.append(
                self._step(
                    "ingest_papers",
                    True,
                    f"已完成 {len(ingested_papers)} / {len(accepted_papers)} 篇论文的深入阅读。",
                    data={"papers": ingested_papers, "errors": ingest_errors},
                )
            )
        else:
            steps.append(
                self._step(
                    "ingest_papers",
                    True,
                    "已跳过深入阅读步骤。",
                    data={"skipped": True},
                )
            )

        rag_indexed_papers = self._index_rag_step(
            steps=steps,
            warnings=warnings,
            ingested_papers=ingested_papers,
            index_rag=index_rag,
            rag_chunk_size=rag_chunk_size,
            rag_chunk_overlap=rag_chunk_overlap,
        )

        if generate_knowledge:
            try:
                knowledge_artifact = self.knowledge_service.generate(KnowledgeGenerateRequest(topic=None))
                knowledge = self._artifact_summary(knowledge_artifact)
                steps.append(
                    self._step(
                        "generate_knowledge",
                        True,
                        f"知识树已生成，来源论文数：{knowledge.get('source_paper_count')}。",
                        data=knowledge,
                    )
                )
            except Exception as exc:
                message = f"知识树生成失败：{exc}"
                warnings.append(message)
                steps.append(self._step("generate_knowledge", False, message, error=str(exc)))
        else:
            steps.append(self._step("generate_knowledge", True, "已跳过知识树生成。", data={"skipped": True}))

        if generate_innovation:
            try:
                innovation_artifact = self.innovation_service.generate(InnovationGenerateRequest(topic=None))
                innovation = self._artifact_summary(innovation_artifact)
                if innovation.get("innovation_json", {}).get("warning"):
                    warnings.append(str(innovation["innovation_json"]["warning"]))
                steps.append(
                    self._step(
                        "generate_innovation",
                        True,
                        f"创新点分析已生成，来源论文数：{innovation.get('source_paper_count')}。",
                        data=innovation,
                    )
                )
            except Exception as exc:
                message = f"创新点生成失败：{exc}"
                warnings.append(message)
                steps.append(self._step("generate_innovation", False, message, error=str(exc)))
        else:
            steps.append(self._step("generate_innovation", True, "已跳过创新点生成。", data={"skipped": True}))

        return finalize(success=True, error=None)

    def _run_dry_run_workflow(
        self,
        *,
        run_id: str,
        topic: str,
        max_results: int,
        accept_top_k: int,
        ingest: bool,
        index_rag: bool,
        rag_chunk_size: int,
        rag_chunk_overlap: int,
        generate_knowledge: bool,
        generate_innovation: bool,
    ) -> ResearchWorkflowResponse:
        warning = "当前为 dry_run 模式，结果仅用于演示流程结构，不代表真实检索或真实生成结果。"
        paper_count = max(1, min(max_results, 20))
        accepted_count = min(accept_top_k, paper_count)

        searched_papers = [
            {
                "id": f"DRY-{index}",
                "title": f"[dry_run/mock] {topic} 示例论文 {index}",
                "url": f"dry_run://papers/{index}",
                "source": "dry_run",
                "status": "found",
                "is_accepted": 0,
                "ingest_status": None,
                "local_summary_path": None,
                "relevance_score": 5 - min(index - 1, 4),
                "worth_reading": "dry_run 示例数据，仅用于演示流程结构。",
                "dry_run": True,
            }
            for index in range(1, paper_count + 1)
        ]
        accepted_papers = [
            {
                **paper,
                "status": "accepted",
                "is_accepted": 1,
            }
            for paper in searched_papers[:accepted_count]
        ]
        ingested_papers = (
            [
                {
                    **paper,
                    "status": "ingested",
                    "ingest_status": "dry_run",
                    "local_summary_path": f"dry_run://summaries/{paper['id']}",
                }
                for paper in accepted_papers
            ]
            if ingest
            else []
        )
        rag_indexed_papers = (
            [
                {
                    "paper_id": str(paper["id"]),
                    "success": True,
                    "chunk_count": 3,
                    "warnings": ["dry_run RAG 索引结果为模拟数据。"],
                    "error": None,
                    "dry_run": True,
                }
                for paper in ingested_papers
            ]
            if index_rag and ingest
            else []
        )

        knowledge = (
            {
                "id": "dry_run-knowledge",
                "topic": topic,
                "source_paper_count": len(accepted_papers),
                "knowledge_tree_markdown": f"# [dry_run/mock] {topic} 知识树\n\n- 核心概念\n- 方法脉络\n- 评测与应用",
                "learning_roadmap_markdown": "# dry_run 学习路径\n\n1. 背景\n2. 方法\n3. 局限与机会",
                "mermaid_mindmap": f"mindmap\n  root(({topic}))\n    dry_run mock data",
                "mermaid_flowchart": "flowchart TD\n  A[search] --> B[accept]\n  B --> C[knowledge]",
                "local_markdown_path": "dry_run://knowledge",
                "generation_method": "dry_run",
                "dry_run": True,
            }
            if generate_knowledge
            else None
        )
        innovation = (
            {
                "id": "dry_run-innovation",
                "topic": topic,
                "source_paper_count": len(accepted_papers),
                "innovation_markdown": f"# [dry_run/mock] {topic} 创新点\n\n- 组合现有方法\n- 改进评测闭环\n- 探索真实场景约束",
                "innovation_json": {
                    "dry_run": True,
                    "warning": warning,
                    "innovation_ideas": [
                        {
                            "title": "dry_run 示例创新点",
                            "description": "该条目仅用于展示响应结构，不代表真实生成结果。",
                        }
                    ],
                },
                "summary_markdown": "# dry_run 创新点摘要\n\n该结果仅用于演示。",
                "generation_method": "dry_run",
                "local_markdown_path": "dry_run://innovation.md",
                "local_json_path": "dry_run://innovation.json",
                "dry_run": True,
            }
            if generate_innovation
            else None
        )

        steps = [
            self._step(
                "search_papers",
                True,
                f"dry_run：已生成 {len(searched_papers)} 条模拟候选论文。",
                data={"count": len(searched_papers), "papers": searched_papers, "dry_run": True},
            ),
            self._step(
                "accept_top_k",
                True,
                f"dry_run：已模拟接收 {len(accepted_papers)} 篇论文。",
                data={"papers": accepted_papers, "errors": [], "dry_run": True},
            ),
            self._step(
                "ingest_papers",
                True,
                f"dry_run：已模拟完成 {len(ingested_papers)} 篇论文的深入阅读。"
                if ingest
                else "dry_run：已跳过深入阅读步骤。",
                data={"papers": ingested_papers, "errors": [], "dry_run": True}
                if ingest
                else {"skipped": True, "dry_run": True},
            ),
            self._step(
                "index_rag",
                True,
                f"dry_run：已模拟为 {len(rag_indexed_papers)} 篇论文建立 RAG v1 索引。"
                if index_rag
                else "dry_run：已跳过 RAG v1 索引。",
                data={
                    "enabled": index_rag,
                    "papers": rag_indexed_papers,
                    "chunk_size": rag_chunk_size,
                    "chunk_overlap": rag_chunk_overlap,
                    "dry_run": True,
                }
                if index_rag
                else {"enabled": False, "skipped": True, "dry_run": True},
            ),
            self._step(
                "generate_knowledge",
                True,
                "dry_run：已生成模拟知识树。" if generate_knowledge else "dry_run：已跳过知识树生成。",
                data=knowledge if generate_knowledge else {"skipped": True, "dry_run": True},
            ),
            self._step(
                "generate_innovation",
                True,
                "dry_run：已生成模拟创新点。" if generate_innovation else "dry_run：已跳过创新点生成。",
                data=innovation if generate_innovation else {"skipped": True, "dry_run": True},
            ),
        ]

        return self._response(
            run_id=run_id,
            success=True,
            topic=topic,
            steps=steps,
            searched_papers=searched_papers,
            accepted_papers=accepted_papers,
            ingested_papers=ingested_papers,
            rag_indexed_papers=rag_indexed_papers,
            knowledge=knowledge,
            innovation=innovation,
            warnings=[warning],
            error=None,
            dry_run=True,
        )

    def latest_workflow(self) -> WorkflowRunDetail | None:
        return self.workflow_repo.latest()

    def list_workflow_history(self, limit: int = 10) -> list[WorkflowRunSummary]:
        return self.workflow_repo.list(limit=limit)

    def get_workflow_detail(self, run_id: str) -> WorkflowRunDetail:
        return self.workflow_repo.get_by_run_id(run_id)

    def _index_rag_step(
        self,
        *,
        steps: list[ResearchWorkflowStep],
        warnings: list[str],
        ingested_papers: list[dict[str, Any]],
        index_rag: bool,
        rag_chunk_size: int,
        rag_chunk_overlap: int,
    ) -> list[dict[str, Any]]:
        if not index_rag:
            steps.append(
                self._step(
                    "index_rag",
                    True,
                    "已跳过 RAG v1 索引。",
                    data={"enabled": False, "skipped": True},
                )
            )
            return []

        rag_results: list[dict[str, Any]] = []
        for paper in ingested_papers:
            paper_id = paper.get("id")
            try:
                result = self.rag_service.index_paper_for_rag(
                    paper_id=str(paper_id),
                    chunk_size=rag_chunk_size,
                    chunk_overlap=rag_chunk_overlap,
                )
                result_data = result.model_dump()
                rag_results.append(
                    {
                        "paper_id": result_data.get("paper_id") or str(paper_id),
                        "success": result_data.get("success"),
                        "chunk_count": result_data.get("chunk_count", 0),
                        "warnings": result_data.get("warnings") or [],
                        "error": result_data.get("error"),
                    }
                )
                for warning in result_data.get("warnings") or []:
                    warnings.append(f"RAG 索引论文 P{paper_id} 提醒：{warning}")
            except Exception as exc:
                message = f"RAG 索引论文 P{paper_id} 失败：{exc}"
                warnings.append(message)
                rag_results.append(
                    {
                        "paper_id": str(paper_id),
                        "success": False,
                        "chunk_count": 0,
                        "warnings": [],
                        "error": str(exc),
                    }
                )

        indexed_count = sum(1 for item in rag_results if item.get("success"))
        total_chunks = sum(int(item.get("chunk_count") or 0) for item in rag_results)
        steps.append(
            self._step(
                "index_rag",
                True,
                f"已为 {indexed_count} / {len(ingested_papers)} 篇论文建立 RAG v1 索引，chunk 总数：{total_chunks}。",
                data={
                    "enabled": True,
                    "papers": rag_results,
                    "indexed_count": indexed_count,
                    "total_chunks": total_chunks,
                    "chunk_size": rag_chunk_size,
                    "chunk_overlap": rag_chunk_overlap,
                },
            )
        )
        return rag_results

    def _paper_summary(self, paper: PaperRead | dict[str, Any]) -> dict[str, Any]:
        data = self._dump(paper)
        return {
            "id": data.get("id"),
            "title": data.get("title"),
            "url": data.get("url"),
            "source": data.get("source"),
            "status": data.get("status"),
            "is_accepted": data.get("is_accepted"),
            "ingest_status": data.get("ingest_status"),
            "local_summary_path": data.get("local_summary_path"),
            "relevance_score": data.get("relevance_score"),
            "worth_reading": data.get("worth_reading"),
        }

    def _artifact_summary(self, artifact: Any) -> dict[str, Any]:
        return self._dump(artifact)

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return dict(value)

    def _step(
        self,
        step: str,
        success: bool,
        summary: str,
        data: Any = None,
        error: str | None = None,
    ) -> ResearchWorkflowStep:
        return ResearchWorkflowStep(
            step=step,
            success=success,
            summary=summary,
            data=data,
            error=error,
        )

    def _response(
        self,
        *,
        run_id: str,
        success: bool,
        topic: str,
        steps: list[ResearchWorkflowStep],
        searched_papers: list[dict[str, Any]],
        accepted_papers: list[dict[str, Any]],
        ingested_papers: list[dict[str, Any]],
        rag_indexed_papers: list[dict[str, Any]],
        knowledge: dict[str, Any] | None,
        innovation: dict[str, Any] | None,
        warnings: list[str],
        error: str | None,
        dry_run: bool = False,
    ) -> ResearchWorkflowResponse:
        return ResearchWorkflowResponse(
            run_id=run_id,
            success=success,
            topic=topic,
            dry_run=dry_run,
            steps=steps,
            searched_papers=searched_papers,
            accepted_papers=accepted_papers,
            ingested_papers=ingested_papers,
            rag_indexed_papers=rag_indexed_papers,
            knowledge=knowledge,
            innovation=innovation,
            warnings=warnings,
            error=error,
        )

    def _persist_response(
        self,
        response: ResearchWorkflowResponse,
        *,
        max_results: int,
        accept_top_k: int,
    ) -> ResearchWorkflowResponse:
        try:
            result = response.model_dump(mode="json")
            self.workflow_repo.create(
                WorkflowRunCreate(
                    run_id=response.run_id or uuid4().hex,
                    topic=response.topic,
                    success=response.success,
                    dry_run=response.dry_run,
                    max_results=max_results,
                    accept_top_k=accept_top_k,
                    searched_count=len(response.searched_papers),
                    accepted_count=len(response.accepted_papers),
                    ingested_count=len(response.ingested_papers),
                    knowledge_generated=response.knowledge is not None,
                    innovation_generated=response.innovation is not None,
                    warnings=response.warnings,
                    result=result,
                    error=response.error,
                )
            )
        except Exception as exc:
            response.warnings.append(f"workflow result persistence failed: {exc}")
        return response
