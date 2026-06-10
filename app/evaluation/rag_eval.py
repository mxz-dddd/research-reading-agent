from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

from app.core import database
from app.repositories.rag_repo import RagChunkRepository
from app.schemas.rag import RagChunkCreate, RagSearchChunk

DEFAULT_CASES_PATH = Path(__file__).with_name("rag_eval_cases.json")

SAMPLE_CHUNKS = [
    RagChunkCreate(
        chunk_id="eval-p1-0",
        paper_id="P1",
        source_type="eval",
        source_path="eval://P1",
        chunk_index=0,
        content="Retrieval augmented generation uses retrieved evidence to ground generation.",
        content_preview="Retrieval augmented generation uses retrieved evidence to ground generation.",
        metadata={"paper_title": "Eval Paper 1"},
    ),
    RagChunkCreate(
        chunk_id="eval-p2-0",
        paper_id="P2",
        source_type="eval",
        source_path="eval://P2",
        chunk_index=0,
        content="Agent planning and tool use help decompose research tasks into executable steps.",
        content_preview="Agent planning and tool use help decompose research tasks into executable steps.",
        metadata={"paper_title": "Eval Paper 2"},
    ),
    RagChunkCreate(
        chunk_id="eval-p3-0",
        paper_id="P3",
        source_type="eval",
        source_path="eval://P3",
        chunk_index=0,
        content="Propagation error correction improves timing systems under noisy observations.",
        content_preview="Propagation error correction improves timing systems under noisy observations.",
        metadata={"paper_title": "Eval Paper 3"},
    ),
]


def load_cases(path: str | Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def seed_eval_chunks(repo: RagChunkRepository) -> None:
    for chunk in SAMPLE_CHUNKS:
        repo.create_chunk(chunk)


def evaluate_cases(
    repo: RagChunkRepository,
    cases: list[dict[str, Any]],
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    hit_count = 0

    for case in cases:
        query = str(case.get("query") or "")
        expected_terms = [str(term).lower() for term in case.get("expected_terms") or []]
        expected_paper_id = str(case.get("expected_paper_id") or "")
        results = repo.search_chunks(query=query, top_k=top_k)
        hit = _is_hit(results, expected_paper_id=expected_paper_id, expected_terms=expected_terms)
        hit_count += 1 if hit else 0
        case_results.append(
            {
                "query": query,
                "expected": {
                    "paper_id": expected_paper_id,
                    "terms": expected_terms,
                },
                "top_results": [_serialize_result(result) for result in results],
                "hit": hit,
            }
        )

    total_cases = len(cases)
    return {
        "total_cases": total_cases,
        "hit_count": hit_count,
        "hit_at_k": hit_count / total_cases if total_cases else 0.0,
        "cases": case_results,
    }


def run_evaluation(
    cases_path: str | Path = DEFAULT_CASES_PATH,
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    original_settings = database.settings
    try:
        with TemporaryDirectory() as tmp_dir:
            database.settings = SimpleNamespace(database_path=str(Path(tmp_dir) / "rag_eval.db"))
            database.init_db()
            repo = RagChunkRepository()
            seed_eval_chunks(repo)
            return evaluate_cases(repo, load_cases(cases_path), top_k=top_k)
    finally:
        database.settings = original_settings


def _is_hit(
    results: list[RagSearchChunk],
    *,
    expected_paper_id: str,
    expected_terms: list[str],
) -> bool:
    for result in results:
        paper_hit = not expected_paper_id or result.paper_id == expected_paper_id
        content = result.content.lower()
        matched_terms = {term.lower() for term in result.matched_terms}
        terms_hit = all(term in matched_terms or term in content for term in expected_terms)
        if paper_hit and terms_hit:
            return True
    return False


def _serialize_result(result: RagSearchChunk) -> dict[str, Any]:
    return {
        "chunk_id": result.chunk_id,
        "paper_id": result.paper_id,
        "chunk_index": result.chunk_index,
        "score": result.score,
        "matched_terms": result.matched_terms,
        "score_reason": result.score_reason,
        "content_preview": result.content_preview,
    }


def main() -> None:
    print(json.dumps(run_evaluation(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
