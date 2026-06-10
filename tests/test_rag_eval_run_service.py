from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.rag_eval_run_service import RagEvalRunService


def _write_run(path: Path, *, total: int, mode: str = "hybrid") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "created_at": "2026-06-09T00:00:00+00:00",
                "base_url": "http://127.0.0.1:8000",
                "golden_file": "eval/golden_queries.example.jsonl",
                "retrieval_modes": [mode],
                "top_k": 5,
                "run_answer": False,
                "summary": {
                    "total": total,
                    "error_count": 0,
                    "avg_recall_expected_terms": 0.5,
                    "avg_recall_expected_chunk_ids": 1.0,
                    "avg_recall_expected_paper_ids": 1.0,
                    "answer_contains_any_rate": None,
                },
                "results": [{"query_id": "gq-1"}],
            }
        ),
        encoding="utf-8",
    )


def test_list_runs_missing_dir_returns_empty(tmp_path: Path) -> None:
    service = RagEvalRunService(tmp_path / "missing")

    assert service.list_runs() == []


def test_list_runs_orders_by_modified_time_desc(tmp_path: Path) -> None:
    runs_dir = tmp_path / "eval" / "rag_eval_runs"
    older = runs_dir / "rag_eval_old.json"
    newer = runs_dir / "rag_eval_new.json"
    _write_run(older, total=1)
    time.sleep(0.01)
    _write_run(newer, total=2)

    items = RagEvalRunService(runs_dir).list_runs()

    assert [item["run_id"] for item in items] == ["rag_eval_new", "rag_eval_old"]
    assert items[0]["total"] == 2


def test_list_runs_returns_summary_without_results(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir / "rag_eval_one.json", total=1)

    item = RagEvalRunService(runs_dir).list_runs()[0]

    assert item["run_id"] == "rag_eval_one"
    assert item["avg_recall_expected_terms"] == 0.5
    assert "results" not in item


def test_get_run_reads_full_json_and_adds_metadata(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir / "rag_eval_one.json", total=1)

    run = RagEvalRunService(runs_dir).get_run("rag_eval_one")

    assert run is not None
    assert run["run_id"] == "rag_eval_one"
    assert run["filename"] == "rag_eval_one.json"
    assert run["results"] == [{"query_id": "gq-1"}]
    assert run["modified_at"]


def test_get_run_rejects_path_traversal(tmp_path: Path) -> None:
    service = RagEvalRunService(tmp_path)

    assert service.get_run("../secret") is None


def test_broken_json_does_not_break_list_runs(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "bad.json").write_text("{bad json", encoding="utf-8")
    _write_run(runs_dir / "good.json", total=1)

    items = RagEvalRunService(runs_dir).list_runs()

    assert len(items) == 2
    assert any(item.get("error") for item in items)
    assert any(item.get("run_id") == "good" for item in items)
