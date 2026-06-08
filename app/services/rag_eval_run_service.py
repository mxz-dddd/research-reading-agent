from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


class RagEvalRunService:
    def __init__(self, runs_dir: str | Path = "eval/rag_eval_runs"):
        self.runs_dir = Path(runs_dir)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.runs_dir.exists():
            return []

        safe_limit = max(1, min(limit, 100))
        paths = sorted(self.runs_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        items = []
        for path in paths[:safe_limit]:
            modified_at = self._modified_at(path)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                items.append(
                    {
                        "run_id": path.stem,
                        "filename": path.name,
                        "modified_at": modified_at,
                        "error": str(exc),
                    }
                )
                continue
            items.append(self.summarize_run(data, filename=path.name, modified_at=modified_at))
        return items

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not self._is_safe_run_id(run_id):
            return None

        filename = run_id if run_id.endswith(".json") else f"{run_id}.json"
        path = self.runs_dir / filename
        if not path.exists() or not path.is_file():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"run_id": path.stem, "filename": path.name, "error": str(exc)}

        result = dict(data) if isinstance(data, dict) else {"data": data}
        result["run_id"] = path.stem
        result["filename"] = path.name
        result["modified_at"] = self._modified_at(path)
        return result

    def summarize_run(
        self,
        data: dict[str, Any],
        filename: str | None = None,
        modified_at: str | None = None,
    ) -> dict[str, Any]:
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        filename_value = filename or str(data.get("filename") or "")
        run_id = filename_value.removesuffix(".json") if filename_value else str(data.get("run_id") or "")
        return {
            "run_id": run_id,
            "filename": filename_value,
            "modified_at": modified_at,
            "created_at": data.get("created_at"),
            "base_url": data.get("base_url"),
            "golden_file": data.get("golden_file"),
            "retrieval_modes": data.get("retrieval_modes") or [],
            "top_k": data.get("top_k"),
            "run_answer": data.get("run_answer"),
            "total": summary.get("total", 0),
            "error_count": summary.get("error_count", 0),
            "avg_recall_expected_terms": summary.get("avg_recall_expected_terms", 0.0),
            "avg_recall_expected_chunk_ids": summary.get("avg_recall_expected_chunk_ids", 0.0),
            "avg_recall_expected_paper_ids": summary.get("avg_recall_expected_paper_ids", 0.0),
            "answer_contains_any_rate": summary.get("answer_contains_any_rate"),
        }

    def _is_safe_run_id(self, run_id: str) -> bool:
        if "/" in run_id or ".." in run_id:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", run_id))

    def _modified_at(self, path: Path) -> str:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
