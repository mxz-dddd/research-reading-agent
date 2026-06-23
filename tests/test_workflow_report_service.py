from pathlib import Path

import pytest
from fastapi import HTTPException

from app.schemas.workflow import WorkflowRunDetail
from app.services.workflow_report_service import DRY_RUN_REPORT_WARNING, WorkflowReportService


def fake_workflow_run(run_id: str = "run_report_001", dry_run: bool = True) -> WorkflowRunDetail:
    return WorkflowRunDetail(
        id=1,
        run_id=run_id,
        topic="large language model agent",
        success=True,
        dry_run=dry_run,
        max_results=2,
        accept_top_k=1,
        searched_count=2,
        accepted_count=1,
        ingested_count=1,
        knowledge_generated=True,
        innovation_generated=True,
        warnings=["dry_run warning"] if dry_run else [],
        error=None,
        created_at="2026-06-04T00:00:00+00:00",
        result={
            "run_id": run_id,
            "success": True,
            "topic": "large language model agent",
            "dry_run": dry_run,
            "steps": [
                {
                    "step": "search_papers",
                    "success": True,
                    "summary": "fake search",
                    "data": {},
                    "error": None,
                },
                {
                    "step": "accept_top_k",
                    "success": True,
                    "summary": "fake accept",
                    "data": {},
                    "error": None,
                },
                {
                    "step": "ingest_papers",
                    "success": True,
                    "summary": "fake ingest",
                    "data": {},
                    "error": None,
                },
                {
                    "step": "generate_knowledge",
                    "success": True,
                    "summary": "fake knowledge",
                    "data": {},
                    "error": None,
                },
                {
                    "step": "generate_innovation",
                    "success": True,
                    "summary": "fake innovation",
                    "data": {},
                    "error": None,
                },
            ],
            "searched_papers": [
                {
                    "id": "DRY-1",
                    "title": "[dry_run/mock] Paper 1",
                    "url": "dry_run://paper/1",
                    "source": "dry_run",
                    "status": "found",
                    "screening_summary": "fake summary",
                }
            ],
            "accepted_papers": [
                {"id": "DRY-1", "title": "[dry_run/mock] Paper 1", "status": "accepted"}
            ],
            "ingested_papers": [
                {
                    "id": "DRY-1",
                    "title": "[dry_run/mock] Paper 1",
                    "status": "ingested",
                    "local_summary_path": "dry_run://summary",
                }
            ],
            "rag_indexed_papers": [
                {
                    "paper_id": "DRY-1",
                    "success": True,
                    "chunk_count": 3,
                    "warnings": ["dry_run RAG 索引结果为模拟数据。"],
                    "error": None,
                    "dry_run": True,
                }
            ],
            "knowledge": {
                "knowledge_tree_markdown": "# Knowledge",
                "learning_roadmap_markdown": "# Roadmap",
                "mermaid_mindmap": "mindmap",
                "mermaid_flowchart": "flowchart TD",
            },
            "innovation": {
                "innovation_markdown": "# Innovation",
                "innovation_json": {"ideas": ["fake"]},
                "summary_markdown": "# Summary",
            },
            "warnings": ["dry_run warning"] if dry_run else [],
            "error": None,
        },
    )


def test_workflow_report_service_generates_and_saves_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = WorkflowReportService()
    monkeypatch.setattr(
        service.workflow_repo, "get_by_run_id", lambda run_id: fake_workflow_run(run_id)
    )
    service.report_dir = tmp_path / "reports"

    result = service.generate_report("run_report_001")

    assert result.success is True
    assert result.run_id == "run_report_001"
    assert result.report_path is not None
    assert Path(result.report_path).exists()
    assert result.report_markdown is not None
    assert "# Research Workflow Report" in result.report_markdown
    assert "## 6. 知识树结果" in result.report_markdown
    assert "## RAG 索引结果" in result.report_markdown
    assert "## 7. 创新点结果" in result.report_markdown


def test_workflow_report_service_dry_run_report_contains_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = WorkflowReportService()
    monkeypatch.setattr(
        service.workflow_repo,
        "get_by_run_id",
        lambda run_id: fake_workflow_run(run_id, dry_run=True),
    )
    service.report_dir = tmp_path / "reports"

    result = service.generate_report("run_report_001")

    assert result.success is True
    assert result.report_markdown is not None
    assert DRY_RUN_REPORT_WARNING in result.report_markdown


def test_workflow_report_service_raises_when_workflow_run_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WorkflowReportService()

    def raise_missing(run_id: str) -> None:
        raise HTTPException(status_code=404, detail="workflow run 不存在")

    monkeypatch.setattr(service.workflow_repo, "get_by_run_id", raise_missing)

    with pytest.raises(HTTPException) as exc_info:
        service.generate_report("missing")

    assert exc_info.value.status_code == 404


def test_workflow_report_service_reads_existing_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = WorkflowReportService()
    monkeypatch.setattr(
        service.workflow_repo, "get_by_run_id", lambda run_id: fake_workflow_run(run_id)
    )
    service.report_dir = tmp_path / "reports"
    generated = service.generate_report("run_report_001")

    result = service.get_report("run_report_001")

    assert result.success is True
    assert result.report_path == generated.report_path
    assert result.report_markdown == generated.report_markdown
