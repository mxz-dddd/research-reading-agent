from pathlib import Path
import json
import re
from typing import Any

from fastapi import HTTPException

from app.repositories.workflow_repo import WorkflowRunRepository
from app.schemas.workflow import WorkflowReportResponse, WorkflowRunDetail


DRY_RUN_REPORT_WARNING = "当前报告基于 dry_run 模式生成，仅用于演示流程结构，不代表真实论文检索或真实模型生成结果。"


class WorkflowReportService:
    def __init__(self) -> None:
        self.workflow_repo = WorkflowRunRepository()
        self.report_dir = Path("data/archives/workflow_reports")

    def generate_report(self, run_id: str | None = None) -> WorkflowReportResponse:
        run = self._resolve_run(run_id)
        report_markdown = self.build_report_markdown(run)
        report_path = self._report_path(run.run_id)
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_markdown, encoding="utf-8")
        except OSError as exc:
            return WorkflowReportResponse(
                success=False,
                run_id=run.run_id,
                report_path=str(report_path),
                report_markdown=None,
                error=f"workflow report 保存失败：{exc}",
            )
        return WorkflowReportResponse(
            success=True,
            run_id=run.run_id,
            report_path=str(report_path),
            report_markdown=report_markdown,
            error=None,
        )

    def get_report(self, run_id: str | None = None) -> WorkflowReportResponse:
        run = self._resolve_run(run_id)
        report_path = self._report_path(run.run_id)
        if not report_path.exists():
            raise HTTPException(status_code=404, detail="workflow report 不存在，请先生成报告")
        try:
            report_markdown = report_path.read_text(encoding="utf-8")
        except OSError as exc:
            return WorkflowReportResponse(
                success=False,
                run_id=run.run_id,
                report_path=str(report_path),
                report_markdown=None,
                error=f"workflow report 读取失败：{exc}",
            )
        return WorkflowReportResponse(
            success=True,
            run_id=run.run_id,
            report_path=str(report_path),
            report_markdown=report_markdown,
            error=None,
        )

    def build_report_markdown(self, run: WorkflowRunDetail) -> str:
        result = run.result or {}
        topic = result.get("topic") or run.topic
        warnings = result.get("warnings") or run.warnings or []
        error = result.get("error") or run.error
        dry_run = bool(result.get("dry_run", run.dry_run))
        lines = [
            "# Research Workflow Report",
            "",
            "## 1. 基本信息",
            "",
            f"- Run ID: `{run.run_id}`",
            f"- Topic: {topic}",
            f"- Success: {result.get('success', run.success)}",
            f"- Dry Run: {dry_run}",
            f"- Created At: {run.created_at}",
            "",
            "## 2. Workflow 执行概览",
            "",
        ]
        if dry_run:
            lines.extend([f"> **{DRY_RUN_REPORT_WARNING}**", ""])
        lines.extend(self._render_steps(result.get("steps") or []))
        lines.extend(self._render_papers("## 3. 搜索论文概览", result.get("searched_papers") or []))
        lines.extend(self._render_papers("## 4. 已接收论文", result.get("accepted_papers") or []))
        lines.extend(self._render_papers("## 5. 深入阅读 / Ingest 结果", result.get("ingested_papers") or []))
        lines.extend(self._render_rag_indexing(result.get("rag_indexed_papers"), result.get("steps") or [], dry_run))
        lines.extend(self._render_knowledge(result.get("knowledge")))
        lines.extend(self._render_innovation(result.get("innovation")))
        lines.extend(self._render_warnings(warnings, error, dry_run))
        lines.extend(self._render_next_steps(result.get("innovation")))
        return "\n".join(lines).rstrip() + "\n"

    def _resolve_run(self, run_id: str | None) -> WorkflowRunDetail:
        if run_id:
            return self.workflow_repo.get_by_run_id(run_id)
        run = self.workflow_repo.latest()
        if run is None:
            raise HTTPException(status_code=404, detail="还没有 workflow run 记录")
        return run

    def _report_path(self, run_id: str) -> Path:
        safe_run_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", run_id).strip("-") or "unknown"
        return self.report_dir / f"workflow_report_{safe_run_id}.md"

    def _render_steps(self, steps: list[dict[str, Any]]) -> list[str]:
        if not steps:
            return ["当前 workflow 结果中未包含 steps。", ""]
        lines = ["| Step | Success | Summary | Error |", "| --- | --- | --- | --- |"]
        for step in steps:
            lines.append(
                "| {step} | {success} | {summary} | {error} |".format(
                    step=self._cell(step.get("step")),
                    success=self._cell(step.get("success")),
                    summary=self._cell(step.get("summary")),
                    error=self._cell(step.get("error")),
                )
            )
        lines.append("")
        return lines

    def _render_papers(self, title: str, papers: list[dict[str, Any]]) -> list[str]:
        lines = ["", title, ""]
        if not papers:
            return lines + ["当前 workflow 结果中未包含该字段。", ""]
        for index, paper in enumerate(papers, start=1):
            lines.extend(
                [
                    f"### {index}. {paper.get('title') or 'Untitled'}",
                    "",
                    f"- ID: {paper.get('id')}",
                    f"- Authors: {paper.get('authors') or '当前 workflow 结果中未包含该字段'}",
                    f"- Published: {paper.get('published_at') or '当前 workflow 结果中未包含该字段'}",
                    f"- Link: {paper.get('url') or '当前 workflow 结果中未包含该字段'}",
                    f"- Source: {paper.get('source') or '当前 workflow 结果中未包含该字段'}",
                    f"- Status: {paper.get('status') or '当前 workflow 结果中未包含该字段'}",
                    f"- Summary: {self._first_available(paper, ['summary', 'screening_summary', 'abstract_summary', 'deep_summary'])}",
                    "",
                ]
            )
        return lines

    def _render_knowledge(self, knowledge: dict[str, Any] | None) -> list[str]:
        lines = ["", "## 6. 知识树结果", ""]
        if not knowledge:
            return lines + ["当前 workflow 结果中未包含该字段。", ""]
        for key in ["knowledge_tree_markdown", "learning_roadmap_markdown", "mermaid_mindmap", "mermaid_flowchart"]:
            lines.extend([f"### {key}", "", str(knowledge.get(key) or "当前 workflow 结果中未包含该字段。"), ""])
        return lines

    def _render_rag_indexing(
        self,
        rag_indexed_papers: list[dict[str, Any]] | None,
        steps: list[dict[str, Any]],
        dry_run: bool,
    ) -> list[str]:
        lines = ["", "## RAG 索引结果", ""]
        index_step = next((step for step in steps if step.get("step") == "index_rag"), None)
        if index_step:
            step_data = index_step.get("data") or {}
            lines.append(f"- Enabled: {step_data.get('enabled', True)}")
            lines.append(f"- Step Summary: {index_step.get('summary')}")
        else:
            lines.append("- Enabled: 当前 workflow 结果中未包含该字段。")

        if dry_run:
            lines.append("- 当前 RAG 索引结果基于 dry_run 模式生成，属于模拟结果。")

        if not rag_indexed_papers:
            lines.extend(["", "当前 workflow 结果中未包含 RAG 索引信息。", ""])
            return lines

        lines.extend(["", "| Paper ID | Success | Chunk Count | Warnings | Error |", "| --- | --- | --- | --- | --- |"])
        for item in rag_indexed_papers:
            warnings = "; ".join(str(warning) for warning in item.get("warnings") or [])
            lines.append(
                "| {paper_id} | {success} | {chunk_count} | {warnings} | {error} |".format(
                    paper_id=self._cell(item.get("paper_id")),
                    success=self._cell(item.get("success")),
                    chunk_count=self._cell(item.get("chunk_count")),
                    warnings=self._cell(warnings),
                    error=self._cell(item.get("error")),
                )
            )
        lines.append("")
        return lines

    def _render_innovation(self, innovation: dict[str, Any] | None) -> list[str]:
        lines = ["", "## 7. 创新点结果", ""]
        if not innovation:
            return lines + ["当前 workflow 结果中未包含该字段。", ""]
        lines.extend(["### innovation_markdown", "", str(innovation.get("innovation_markdown") or "当前 workflow 结果中未包含该字段。"), ""])
        lines.extend(["### innovation_json", "", "```json", json.dumps(innovation.get("innovation_json") or {}, ensure_ascii=False, indent=2), "```", ""])
        lines.extend(["### summary_markdown", "", str(innovation.get("summary_markdown") or "当前 workflow 结果中未包含该字段。"), ""])
        return lines

    def _render_warnings(self, warnings: list[str], error: str | None, dry_run: bool) -> list[str]:
        lines = ["", "## 8. Warnings / Errors", ""]
        if dry_run:
            lines.extend([f"- **{DRY_RUN_REPORT_WARNING}**"])
        if warnings:
            lines.extend(f"- {warning}" for warning in warnings)
        if error:
            lines.append(f"- Error: {error}")
        if not dry_run and not warnings and not error:
            lines.append("暂无 warnings 或 errors。")
        lines.append("")
        return lines

    def _render_next_steps(self, innovation: dict[str, Any] | None) -> list[str]:
        lines = ["", "## 9. 后续研究建议", ""]
        if innovation and innovation.get("innovation_markdown"):
            lines.extend(
                [
                    "可优先复核上方创新点结果，挑选其中有明确 evidence 或 gap 描述的方向继续推进。",
                    "建议下一步补充真实论文证据、实验可行性和评价指标，再决定是否进入 RAG 或原型验证。",
                    "",
                ]
            )
            return lines
        lines.extend(
            [
                "- 先补充更多已接收论文，避免基于过少材料得出结论。",
                "- 优先检查每篇论文的方法、实验设置和局限性。",
                "- 在没有明确创新点结果时，不建议直接声称已有具体研究结论。",
                "",
            ]
        )
        return lines

    def _first_available(self, paper: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = paper.get(key)
            if value:
                return str(value)
        return "当前 workflow 结果中未包含该字段。"

    def _cell(self, value: Any) -> str:
        text = "" if value is None else str(value)
        return text.replace("|", "\\|").replace("\n", " ")
