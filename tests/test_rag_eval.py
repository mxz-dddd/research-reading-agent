import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.evaluation.rag_eval import evaluate_cases, run_evaluation, seed_eval_chunks
from app.repositories.rag_repo import RagChunkRepository


@pytest.fixture()
def rag_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RagChunkRepository:
    test_db = tmp_path / "rag_eval_test.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    repo = RagChunkRepository()
    seed_eval_chunks(repo)
    return repo


def test_rag_eval_core_function_reports_hits(rag_repo: RagChunkRepository) -> None:
    result = evaluate_cases(
        rag_repo,
        [
            {
                "query": "retrieval augmented generation",
                "expected_terms": ["retrieval", "generation"],
                "expected_paper_id": "P1",
            }
        ],
        top_k=3,
    )

    assert result["total_cases"] == 1
    assert result["hit_count"] == 1
    assert result["hit_at_k"] == 1.0
    assert result["cases"][0]["hit"] is True
    assert result["cases"][0]["top_results"][0]["matched_terms"]


def test_rag_eval_run_evaluation_uses_temporary_database() -> None:
    result = run_evaluation(top_k=3)

    assert result["total_cases"] >= 1
    assert result["hit_count"] >= 1
    assert "cases" in result
