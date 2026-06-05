import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.repositories.workflow_repo import WorkflowRunRepository
from app.schemas.workflow import WorkflowRunCreate


def sample_workflow_run(run_id: str, topic: str = "llm agent") -> WorkflowRunCreate:
    return WorkflowRunCreate(
        run_id=run_id,
        topic=topic,
        success=True,
        dry_run=True,
        max_results=3,
        accept_top_k=2,
        searched_count=3,
        accepted_count=2,
        ingested_count=2,
        knowledge_generated=True,
        innovation_generated=True,
        warnings=["dry_run warning"],
        result={
            "run_id": run_id,
            "success": True,
            "topic": topic,
            "dry_run": True,
            "warnings": ["dry_run warning"],
        },
        error=None,
    )


@pytest.fixture()
def workflow_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WorkflowRunRepository:
    test_db = tmp_path / "workflow_test.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return WorkflowRunRepository()


def test_workflow_repo_saves_and_gets_by_run_id(workflow_repo: WorkflowRunRepository) -> None:
    created = workflow_repo.create(sample_workflow_run("run-001"))

    found = workflow_repo.get_by_run_id("run-001")

    assert created.run_id == "run-001"
    assert found.run_id == "run-001"
    assert found.topic == "llm agent"
    assert found.dry_run is True
    assert found.warnings == ["dry_run warning"]
    assert found.result["run_id"] == "run-001"


def test_workflow_repo_gets_latest(workflow_repo: WorkflowRunRepository) -> None:
    workflow_repo.create(sample_workflow_run("run-001", topic="first"))
    workflow_repo.create(sample_workflow_run("run-002", topic="second"))

    latest = workflow_repo.latest()

    assert latest is not None
    assert latest.run_id == "run-002"
    assert latest.topic == "second"


def test_workflow_repo_lists_history(workflow_repo: WorkflowRunRepository) -> None:
    workflow_repo.create(sample_workflow_run("run-001", topic="first"))
    workflow_repo.create(sample_workflow_run("run-002", topic="second"))

    history = workflow_repo.list(limit=1)

    assert len(history) == 1
    assert history[0].run_id == "run-002"
    assert history[0].searched_count == 3
    assert history[0].warnings == ["dry_run warning"]
