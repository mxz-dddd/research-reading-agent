from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app


def _write_run(base: Path, run_id: str = "rag_eval_one") -> Path:
    path = base / "eval" / "rag_eval_runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "created_at": "2026-06-09T00:00:00+00:00",
                "base_url": "http://127.0.0.1:8000",
                "golden_file": "eval/golden_queries.example.jsonl",
                "retrieval_modes": ["hybrid", "keyword"],
                "top_k": 5,
                "run_answer": True,
                "summary": {
                    "total": 12,
                    "error_count": 0,
                    "avg_recall_expected_terms": 0.5,
                    "avg_recall_expected_chunk_ids": 1.0,
                    "avg_recall_expected_paper_ids": 1.0,
                    "answer_contains_any_rate": 0.25,
                },
                "results": [{"query_id": "gq-1", "retrieval_mode": "hybrid"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_list_eval_runs_missing_dir_returns_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    response = client.get("/api/rag/eval-runs")

    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_list_eval_runs_returns_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write_run(tmp_path)
    client = TestClient(app)

    response = client.get("/api/rag/eval-runs")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["run_id"] == "rag_eval_one"
    assert data["items"][0]["total"] == 12
    assert "results" not in data["items"][0]


def test_get_eval_run_returns_full_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write_run(tmp_path)
    client = TestClient(app)

    response = client.get("/api/rag/eval-runs/rag_eval_one")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "rag_eval_one"
    assert data["filename"] == "rag_eval_one.json"
    assert data["results"] == [{"query_id": "gq-1", "retrieval_mode": "hybrid"}]


def test_get_eval_run_missing_returns_404(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    response = client.get("/api/rag/eval-runs/not-found")

    assert response.status_code == 404
    assert "eval run not found" in response.json()["detail"]


def test_list_eval_runs_limit_over_100_returns_422(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    response = client.get("/api/rag/eval-runs?limit=101")

    assert response.status_code == 422


def test_get_eval_run_rejects_path_traversal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    response = client.get("/api/rag/eval-runs/..%2Fsecret")

    assert response.status_code == 404
