from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.innovation import InnovationArtifactRead
from app.schemas.knowledge import KnowledgeArtifactRead
from app.schemas.paper import PaperRead
from app.schemas.workflow import ResearchWorkflowRequest
from app.services.research_workflow_service import ResearchWorkflowService


def fake_paper(paper_id: int, title: str, status: str = "found", is_accepted: int = 0) -> PaperRead:
    return PaperRead(
        id=paper_id,
        topic_id=None,
        title=title,
        authors="Test Author",
        abstract="Fake abstract",
        url=f"https://example.com/{paper_id}",
        source="mock",
        published_at="2026-01-01",
        summary=None,
        screening_summary="Fake screening",
        relevance_score=4,
        worth_reading="值得继续看",
        is_accepted=is_accepted,
        accepted_at=None,
        pdf_url=None,
        local_pdf_path=None,
        local_text_path=None,
        local_summary_path=None,
        abstract_summary=None,
        deep_summary=None,
        ingest_status=None,
        status=status,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def fake_knowledge() -> KnowledgeArtifactRead:
    return KnowledgeArtifactRead(
        id=1,
        topic=None,
        source_paper_count=2,
        knowledge_tree_markdown="# Knowledge",
        learning_roadmap_markdown="# Roadmap",
        mermaid_mindmap="mindmap",
        mermaid_flowchart="flowchart TD",
        local_markdown_path="data/archives/knowledge/fake.md",
        generation_method="fallback",
        created_at="2026-01-01T00:00:00Z",
    )


def fake_innovation() -> InnovationArtifactRead:
    return InnovationArtifactRead(
        id=1,
        topic=None,
        source_paper_count=2,
        innovation_markdown="# Innovation",
        innovation_json={"warning": None, "innovation_ideas": []},
        summary_markdown="# Summary",
        generation_method="fallback",
        local_markdown_path="data/archives/innovation/fake.md",
        local_json_path="data/archives/innovation/fake.json",
        created_at="2026-01-01T00:00:00Z",
    )


def fake_rag_index(
    paper_id: str, chunk_count: int = 3, warnings: list[str] | None = None, error: str | None = None
) -> Any:
    success = error is None
    return SimpleNamespace(
        model_dump=lambda: {
            "success": success,
            "paper_id": str(paper_id),
            "chunk_count": chunk_count if success else 0,
            "warnings": warnings or [],
            "error": error,
        }
    )


def test_workflow_runs_steps_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ResearchWorkflowService()
    monkeypatch.setattr(service.workflow_repo, "create", lambda payload: None)
    calls: list[str] = []
    papers = [fake_paper(1, "Paper 1"), fake_paper(2, "Paper 2")]

    def fake_search(payload: Any) -> list[PaperRead]:
        calls.append("search")
        return papers

    def fake_accept(payload: Any) -> PaperRead:
        calls.append(f"accept:{payload.paper_id}")
        return fake_paper(
            payload.paper_id, f"Paper {payload.paper_id}", status="accepted", is_accepted=1
        )

    def fake_ingest(payload: Any) -> PaperRead:
        calls.append(f"ingest:{payload.paper_id}")
        paper = fake_paper(
            payload.paper_id, f"Paper {payload.paper_id}", status="ingested", is_accepted=1
        )
        return paper.model_copy(
            update={"ingest_status": "abstract_only", "local_summary_path": "fake.md"}
        )

    def fake_index(paper_id: str, chunk_size: int, chunk_overlap: int) -> Any:
        calls.append(f"rag:{paper_id}:{chunk_size}:{chunk_overlap}")
        return fake_rag_index(paper_id)

    monkeypatch.setattr(service.paper_service, "search_and_store", fake_search)
    monkeypatch.setattr(service.paper_service, "accept_paper", fake_accept)
    monkeypatch.setattr(service.paper_service, "ingest_paper", fake_ingest)
    monkeypatch.setattr(service.rag_service, "index_paper_for_rag", fake_index)
    monkeypatch.setattr(service.knowledge_service, "generate", lambda payload: fake_knowledge())
    monkeypatch.setattr(service.innovation_service, "generate", lambda payload: fake_innovation())

    result = service.run(ResearchWorkflowRequest(topic="llm agent", max_results=2, accept_top_k=2))

    assert result.success is True
    assert result.run_id
    assert calls == [
        "search",
        "accept:1",
        "accept:2",
        "ingest:1",
        "ingest:2",
        "rag:1:800:120",
        "rag:2:800:120",
    ]
    assert [step.step for step in result.steps] == [
        "search_papers",
        "accept_top_k",
        "ingest_papers",
        "index_rag",
        "generate_knowledge",
        "generate_innovation",
    ]
    assert len(result.searched_papers) == 2
    assert len(result.accepted_papers) == 2
    assert len(result.ingested_papers) == 2
    assert len(result.rag_indexed_papers) == 2
    assert sum(item["chunk_count"] for item in result.rag_indexed_papers) == 6
    assert result.knowledge is not None
    assert result.innovation is not None


def test_workflow_fails_safely_when_search_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ResearchWorkflowService()
    monkeypatch.setattr(service.workflow_repo, "create", lambda payload: None)
    monkeypatch.setattr(service.paper_service, "search_and_store", lambda payload: [])

    result = service.run(ResearchWorkflowRequest(topic="empty topic"))

    assert result.success is False
    assert result.error == "没有搜索到候选论文，workflow 已停止。"
    assert result.searched_papers == []
    assert result.accepted_papers == []
    assert result.steps[0].step == "search_papers"


def test_workflow_records_ingest_failure_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ResearchWorkflowService()
    monkeypatch.setattr(service.workflow_repo, "create", lambda payload: None)
    papers = [fake_paper(1, "Paper 1"), fake_paper(2, "Paper 2")]
    rag_calls: list[str] = []

    monkeypatch.setattr(service.paper_service, "search_and_store", lambda payload: papers)
    monkeypatch.setattr(
        service.paper_service,
        "accept_paper",
        lambda payload: fake_paper(
            payload.paper_id, f"Paper {payload.paper_id}", status="accepted", is_accepted=1
        ),
    )

    def fake_ingest(payload: Any) -> PaperRead:
        if payload.paper_id == 2:
            raise RuntimeError("fake ingest failed")
        paper = fake_paper(
            payload.paper_id, f"Paper {payload.paper_id}", status="ingested", is_accepted=1
        )
        return paper.model_copy(update={"ingest_status": "abstract_only"})

    monkeypatch.setattr(service.paper_service, "ingest_paper", fake_ingest)
    monkeypatch.setattr(
        service.rag_service,
        "index_paper_for_rag",
        lambda paper_id, chunk_size, chunk_overlap: (
            rag_calls.append(paper_id) or fake_rag_index(paper_id)
        ),
    )
    monkeypatch.setattr(service.knowledge_service, "generate", lambda payload: fake_knowledge())
    monkeypatch.setattr(service.innovation_service, "generate", lambda payload: fake_innovation())

    result = service.run(ResearchWorkflowRequest(topic="llm agent", max_results=2, accept_top_k=2))

    assert result.success is True
    assert len(result.ingested_papers) == 1
    assert any("深入阅读论文 P2 失败" in warning for warning in result.warnings)
    assert rag_calls == ["1"]
    assert len(result.rag_indexed_papers) == 1
    ingest_step = next(step for step in result.steps if step.step == "ingest_papers")
    assert ingest_step.data["errors"] == [{"paper_id": 2, "error": "fake ingest failed"}]


def test_workflow_dry_run_uses_mock_data_without_real_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ResearchWorkflowService()
    monkeypatch.setattr(service.workflow_repo, "create", lambda payload: None)

    def fail_if_called(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry_run should not call real services")

    monkeypatch.setattr(service.paper_service, "search_and_store", fail_if_called)
    monkeypatch.setattr(service.paper_service, "accept_paper", fail_if_called)
    monkeypatch.setattr(service.paper_service, "ingest_paper", fail_if_called)
    monkeypatch.setattr(service.rag_service, "index_paper_for_rag", fail_if_called)
    monkeypatch.setattr(service.knowledge_service, "generate", fail_if_called)
    monkeypatch.setattr(service.innovation_service, "generate", fail_if_called)

    result = service.run(
        ResearchWorkflowRequest(
            topic="large language model agent",
            max_results=3,
            accept_top_k=2,
            dry_run=True,
        )
    )

    assert result.success is True
    assert result.dry_run is True
    assert [step.step for step in result.steps] == [
        "search_papers",
        "accept_top_k",
        "ingest_papers",
        "index_rag",
        "generate_knowledge",
        "generate_innovation",
    ]
    assert len(result.searched_papers) == 3
    assert len(result.accepted_papers) == 2
    assert len(result.ingested_papers) == 2
    assert len(result.rag_indexed_papers) == 2
    assert all(paper["dry_run"] is True for paper in result.searched_papers)
    assert result.knowledge is not None
    assert result.knowledge["dry_run"] is True
    assert result.innovation is not None
    assert result.innovation["dry_run"] is True
    assert any("dry_run 模式" in warning for warning in result.warnings)


def test_workflow_records_rag_index_failure_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ResearchWorkflowService()
    monkeypatch.setattr(service.workflow_repo, "create", lambda payload: None)
    papers = [fake_paper(1, "Paper 1"), fake_paper(2, "Paper 2")]

    monkeypatch.setattr(service.paper_service, "search_and_store", lambda payload: papers)
    monkeypatch.setattr(
        service.paper_service,
        "accept_paper",
        lambda payload: fake_paper(
            payload.paper_id, f"Paper {payload.paper_id}", status="accepted", is_accepted=1
        ),
    )
    monkeypatch.setattr(
        service.paper_service,
        "ingest_paper",
        lambda payload: fake_paper(
            payload.paper_id, f"Paper {payload.paper_id}", status="ingested", is_accepted=1
        ),
    )

    def fake_index(paper_id: str, chunk_size: int, chunk_overlap: int) -> Any:
        if paper_id == "2":
            raise RuntimeError("fake rag failed")
        return fake_rag_index(paper_id, chunk_count=4, warnings=["low text quality"])

    monkeypatch.setattr(service.rag_service, "index_paper_for_rag", fake_index)
    monkeypatch.setattr(service.knowledge_service, "generate", lambda payload: fake_knowledge())
    monkeypatch.setattr(service.innovation_service, "generate", lambda payload: fake_innovation())

    result = service.run(ResearchWorkflowRequest(topic="llm agent", max_results=2, accept_top_k=2))

    assert result.success is True
    assert len(result.rag_indexed_papers) == 2
    assert result.rag_indexed_papers[0]["success"] is True
    assert result.rag_indexed_papers[1]["success"] is False
    assert any("RAG 索引论文 P2 失败" in warning for warning in result.warnings)


def test_workflow_skips_rag_index_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ResearchWorkflowService()
    monkeypatch.setattr(service.workflow_repo, "create", lambda payload: None)
    papers = [fake_paper(1, "Paper 1")]

    monkeypatch.setattr(service.paper_service, "search_and_store", lambda payload: papers)
    monkeypatch.setattr(
        service.paper_service,
        "accept_paper",
        lambda payload: fake_paper(payload.paper_id, "Paper 1", status="accepted", is_accepted=1),
    )
    monkeypatch.setattr(
        service.paper_service,
        "ingest_paper",
        lambda payload: fake_paper(payload.paper_id, "Paper 1", status="ingested", is_accepted=1),
    )
    monkeypatch.setattr(
        service.rag_service,
        "index_paper_for_rag",
        lambda *args, **kwargs: pytest.fail("RAG should be skipped"),
    )
    monkeypatch.setattr(service.knowledge_service, "generate", lambda payload: fake_knowledge())
    monkeypatch.setattr(service.innovation_service, "generate", lambda payload: fake_innovation())

    result = service.run(ResearchWorkflowRequest(topic="llm agent", index_rag=False))

    assert result.success is True
    assert result.rag_indexed_papers == []
    rag_step = next(step for step in result.steps if step.step == "index_rag")
    assert rag_step.data["skipped"] is True
