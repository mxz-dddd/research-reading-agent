import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError


def load_smoke_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_rag_v2.py"
    spec = importlib.util.spec_from_file_location("smoke_rag_v2", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_smoke_script_imports() -> None:
    module = load_smoke_module()

    assert module._join_url("http://127.0.0.1:8000", "/health") == "http://127.0.0.1:8000/health"


def test_join_url_handles_slashes() -> None:
    module = load_smoke_module()

    assert (
        module._join_url("http://localhost:8000/", "/api/rag/search")
        == "http://localhost:8000/api/rag/search"
    )
    assert (
        module._join_url("http://localhost:8000", "api/rag/search")
        == "http://localhost:8000/api/rag/search"
    )


def test_extract_context_pack_id_supports_top_level_and_nested() -> None:
    module = load_smoke_module()

    assert module._extract_context_pack_id({"context_pack_id": "ctx-top"}) == "ctx-top"
    assert (
        module._extract_context_pack_id({"context_pack": {"context_pack_id": "ctx-nested"}})
        == "ctx-nested"
    )
    assert module._extract_context_pack_id({"context_pack": {"id": "ctx-id"}}) == "ctx-id"
    assert (
        module._extract_context_pack_id({"missing": True}, {"context_pack_id": "ctx-second"})
        == "ctx-second"
    )
    assert module._extract_context_pack_id({"missing": True}) is None


def test_evidence_items_uses_first_non_empty_supported_field() -> None:
    module = load_smoke_module()

    response = {
        "chunks": [],
        "evidence": [{"chunk_id": "chunk-1"}, "bad-item"],
        "results": [{"chunk_id": "chunk-2"}],
    }

    assert module._evidence_items(response) == [{"chunk_id": "chunk-1"}]


def test_count_context_item_types_ignores_non_dict_items() -> None:
    module = load_smoke_module()

    counts = module._count_context_item_types(
        [
            {"item_type": "rag_evidence"},
            {"item_type": "rag_evidence"},
            {"item_type": "active_paper"},
            {"other": "ignored"},
            "bad-item",
        ]
    )

    assert counts == {"rag_evidence": 2, "active_paper": 1}


def test_build_payload_omits_empty_paper_id() -> None:
    module = load_smoke_module()
    args = SimpleNamespace(
        query="q",
        top_k=5,
        user_id="default",
        session_id="smoke",
        retrieval_mode="hybrid",
        paper_id=None,
    )

    payload = module._build_payload(args)

    assert payload == {
        "query": "q",
        "top_k": 5,
        "user_id": "default",
        "session_id": "smoke",
        "retrieval_mode": "hybrid",
    }


def test_build_payload_includes_paper_id_when_present() -> None:
    module = load_smoke_module()
    args = SimpleNamespace(
        query="q",
        top_k=3,
        user_id="u1",
        session_id="s1",
        retrieval_mode="keyword",
        paper_id="42",
    )

    payload = module._build_payload(args)

    assert payload["paper_id"] == "42"


def test_request_json_decodes_successful_json(monkeypatch) -> None:
    module = load_smoke_module()

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return b'{"success": true}'

    def fake_urlopen(request, timeout):
        assert request.get_method() == "POST"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-type"] == "application/json"
        assert timeout == 20
        return FakeResponse()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    status, body, raw = module._request_json("POST", "http://test.local/api", {"hello": "world"})

    assert status == 200
    assert body == {"success": True}
    assert raw == '{"success": true}'


def test_request_json_returns_http_error_body(monkeypatch) -> None:
    module = load_smoke_module()

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            404,
            "not found",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"missing"}'),
        )

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    status, body, raw = module._request_json("GET", "http://test.local/missing")

    assert status == 404
    assert body is None
    assert raw == '{"detail":"missing"}'


def test_request_json_returns_url_error_without_network(monkeypatch) -> None:
    module = load_smoke_module()

    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    status, body, raw = module._request_json("GET", "http://test.local/health")

    assert status == 0
    assert body is None
    assert "connection refused" in raw
