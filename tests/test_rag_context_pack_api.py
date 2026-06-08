import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import database
from app.main import app
from app.repositories.context_repo import ContextPackRepository
from app.schemas.context import ContextItem, ContextPackRead


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    test_db = tmp_path / "rag_context_pack_api.db"
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_path=str(test_db)))
    database.init_db()
    return TestClient(app)


def _create_context_pack(
    *,
    user_id: str = "default",
    session_id: str = "default",
    query: str = "What evidence supports contextual retrieval?",
) -> ContextPackRead:
    return ContextPackRepository().create_context_pack(
        user_id=user_id,
        session_id=session_id,
        query=query,
        mode="answer",
        paper_id="paper-1",
        items=[
            ContextItem(
                item_type="rag_evidence",
                source_type="rag_chunk",
                source_id="chunk-1",
                content="Contextual retrieval keeps evidence close to the answer.",
                score=1.2,
                reason="test evidence",
                metadata={"chunk_index": 0},
            )
        ],
    )


def test_get_context_pack_reads_saved_pack(client: TestClient) -> None:
    pack = _create_context_pack()

    response = client.get(f"/api/rag/context-packs/{pack.context_pack_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["context_pack_id"] == pack.context_pack_id
    assert data["items"]
    assert data["item_count"] == 1


def test_get_context_pack_missing_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/rag/context-packs/not-exist")

    assert response.status_code == 404
    assert "context_pack_id not found" in response.json()["detail"]


def test_list_context_packs_returns_items_and_count(client: TestClient) -> None:
    _create_context_pack(query="first query")
    _create_context_pack(query="second query")

    response = client.get("/api/rag/context-packs?user_id=default&session_id=default&limit=5")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "count" in data
    assert data["count"] == len(data["items"])
    assert data["count"] == 2


def test_list_context_packs_limit_over_50_returns_422(client: TestClient) -> None:
    response = client.get("/api/rag/context-packs?user_id=default&session_id=default&limit=51")

    assert response.status_code == 422
