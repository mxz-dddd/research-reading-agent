from types import SimpleNamespace

from app.agent.answer_builder import build_final_answer
from app.agent.orchestrator import AgentOrchestrator
from app.agent.tool_registry import ToolRegistry
from app.schemas.agent import AgentQueryRequest


def test_batch_ingest_continues_after_single_failure(monkeypatch) -> None:
    registry = ToolRegistry()
    monkeypatch.setattr(
        registry.paper_service,
        "get_paper",
        lambda paper_id: SimpleNamespace(title=f"Paper {paper_id}"),
    )

    def fake_ingest(payload):
        if payload.paper_id == 102:
            raise ValueError("PDF 下载失败")
        return SimpleNamespace(
            title=f"Paper {payload.paper_id}",
            ingest_status="pdf_text" if payload.paper_id == 101 else "abstract_only",
        )

    monkeypatch.setattr(registry.paper_service, "ingest_paper", fake_ingest)

    result = registry.batch_ingest_papers(
        paper_ids=[101, 102, 103],
        source_positions=[1, 2, 3],
    )

    assert result["total"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert [item["status"] for item in result["items"]] == ["success", "failed", "success"]


def test_batch_ingest_answer_hides_internal_fields() -> None:
    data = {
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "items": [
            {"position": 1, "paper_id": 101, "title": "A", "status": "success", "ingest_status": "pdf_text"},
            {"position": 2, "paper_id": 102, "title": "B", "status": "failed", "error": "PDF 下载失败"},
        ],
    }

    answer = build_final_answer(
        "batch_ingest_papers",
        data,
        arguments={"paper_ids": [101, 102], "source_positions": [1, 2]},
    )

    assert "1. A" in answer
    assert "阅读方式：PDF全文" in answer
    assert "2. B" in answer
    assert "原因：PDF 下载失败" in answer
    for internal in ("batch_ingest_papers", "ingest_paper", "read_papers", "paper_ids", "routing_method", "chosen_tool"):
        assert internal not in answer


def test_agent_normalizes_read_papers_alias(monkeypatch) -> None:
    orchestrator = AgentOrchestrator()
    captured: dict[str, object] = {}

    def fake_call(tool_name, **arguments):
        captured.update({"tool_name": tool_name, "arguments": arguments})
        return {"total": 1, "succeeded": 1, "failed": 0, "items": []}

    monkeypatch.setattr(orchestrator.registry, "call", fake_call)
    response = orchestrator.query_with_route(
        AgentQueryRequest(message="全部深入阅读"),
        tool_name="read_papers",
        arguments={"paper_ids": [101], "source_positions": [1]},
    )

    assert response.success is True
    assert response.chosen_tool == "batch_ingest_papers"
    assert captured["tool_name"] == "batch_ingest_papers"
    assert "read_papers" not in response.final_answer


def test_unknown_tool_name_is_not_exposed_to_user() -> None:
    response = AgentOrchestrator().query_with_route(
        AgentQueryRequest(message="处理刚才的论文"),
        tool_name="invented_reader_tool",
        arguments={},
    )

    assert response.success is False
    assert "未知工具" not in response.final_answer
    assert "invented_reader_tool" not in response.final_answer
