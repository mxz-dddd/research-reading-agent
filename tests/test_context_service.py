import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.repositories.context_repo import ContextPackRepository
from app.repositories.session_repo import SessionStateRepository
from app.schemas.rag import RagSearchChunk
from app.services.context_service import ContextService


@pytest.fixture()
def context_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ContextService:
    test_db = tmp_path / "context_service.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return ContextService()


def test_context_service_builds_and_persists_context_pack(context_service: ContextService) -> None:
    SessionStateRepository().save_recent_search_results(
        "u1",
        "s1",
        [{"id": 101, "title": "Propagation Paper"}, {"id": 102, "title": "Timing Paper"}],
    )
    evidence = [
        RagSearchChunk(
            score=1.2,
            chunk_id="chunk-a",
            paper_id="101",
            chunk_index=0,
            matched_terms=["propagation"],
            content="Propagation error correction evidence.",
            content_preview="Propagation error correction evidence.",
            retrieval_scores={"sparse": 1.0, "dense": 0.4, "rrf": 0.03},
            rerank_score=1.5,
            section_title="Introduction",
            contextual_header="Paper: Propagation Paper\nSection: Introduction\nChunk: 0\nSource: local_text",
            score_reason="test evidence",
        )
    ]

    pack = context_service.build_context_pack(
        query="What is propagation error?",
        mode="answer",
        evidence_chunks=evidence,
        user_id="u1",
        session_id="s1",
    )
    loaded = ContextPackRepository().get_context_pack(pack.context_pack_id)

    assert loaded is not None
    assert loaded.context_pack_id == pack.context_pack_id
    assert loaded.item_count == 2
    assert {item.item_type for item in loaded.items} == {
        "session_recent_search_results",
        "rag_evidence",
    }
    evidence_item = [item for item in loaded.items if item.item_type == "rag_evidence"][0]
    assert evidence_item.source_id == "chunk-a"
    assert evidence_item.metadata["section_title"] == "Introduction"
