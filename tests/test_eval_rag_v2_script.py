from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_eval_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "eval_rag_v2.py"
    spec = importlib.util.spec_from_file_location("eval_rag_v2", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_eval_script_imports_and_joins_url() -> None:
    module = load_eval_module()

    assert module._join_url("http://127.0.0.1:8000/", "/health") == "http://127.0.0.1:8000/health"


def test_parse_retrieval_modes() -> None:
    module = load_eval_module()

    assert module._parse_retrieval_modes("hybrid, keyword") == ["hybrid", "keyword"]


def test_build_payload_omits_empty_paper_id() -> None:
    module = load_eval_module()
    golden_query = module.GoldenQuery(query_id="gq-1", query="method")

    payload = module._build_payload(
        golden_query,
        retrieval_mode="hybrid",
        top_k=5,
        user_id="default",
        session_id="eval",
    )

    assert payload == {
        "query": "method",
        "top_k": 5,
        "user_id": "default",
        "session_id": "eval",
        "retrieval_mode": "hybrid",
    }


def test_run_eval_uses_monkeypatched_http_and_writes_output(monkeypatch, tmp_path: Path) -> None:
    module = load_eval_module()
    golden_file = tmp_path / "golden.jsonl"
    golden_file.write_text(
        json.dumps(
            {
                "query_id": "gq-1",
                "query": "What is the method?",
                "expected_terms": ["method"],
                "must_contain_any": ["method"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "result.json"
    requests_seen = []

    def fake_get_json(base_url, path):
        assert base_url == "http://test.local"
        assert path == "/health"
        return 200, {"status": "ok"}, '{"status":"ok"}'

    def fake_post_json(base_url, path, payload):
        requests_seen.append((path, payload))
        if path == "/api/rag/search":
            return (
                200,
                {
                    "chunks": [{"chunk_id": "chunk-1", "paper_id": "paper-1", "content": "method evidence"}],
                    "context_pack_id": "ctx-1",
                    "pipeline": {"retrieval_mode": payload["retrieval_mode"]},
                },
                "{}",
            )
        if path == "/api/rag/answer":
            return 200, {"answer": "The method is retrieval.", "context_pack_id": "ctx-2"}, "{}"
        raise AssertionError(path)

    monkeypatch.setattr(module, "_get_json", fake_get_json)
    monkeypatch.setattr(module, "_post_json", fake_post_json)
    args = module.parse_args(
        [
            "--base-url",
            "http://test.local",
            "--golden-file",
            str(golden_file),
            "--retrieval-modes",
            "hybrid",
            "--top-k",
            "3",
            "--run-answer",
            "--output",
            str(output),
        ]
    )

    exit_code, result = module.run_eval(args)

    assert exit_code == 0
    assert result is not None
    assert result["summary"]["total"] == 1
    assert result["summary"]["avg_recall_expected_terms"] == 1.0
    assert result["results"][0]["answer_contains_any"] is True
    assert output.exists()
    assert [request[0] for request in requests_seen] == ["/api/rag/search", "/api/rag/answer"]
