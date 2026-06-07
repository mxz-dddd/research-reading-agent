import asyncio

from app.services.tool_mux import ToolMux, ToolRegistry


def run(coro):
    return asyncio.run(coro)


def test_call_success() -> None:
    registry = ToolRegistry()
    registry.register("get_fake", lambda value: {"value": value}, read_only=True)
    mux = ToolMux(registry=registry)

    result = run(mux.call("get_fake", {"value": 42}))

    assert result["success"] is True
    assert result["result"] == {"value": 42}


def test_unknown_tool_returns_error() -> None:
    mux = ToolMux(registry=ToolRegistry())

    result = run(mux.call("not_exists", {}))

    assert result["success"] is False
    assert "unknown tool" in result["error"]


def test_parallel_partial_failure() -> None:
    registry = ToolRegistry()
    registry.register("ok", lambda value: value, read_only=True)

    def broken_tool() -> None:
        raise RuntimeError("boom")

    registry.register("broken_tool", broken_tool, read_only=False)
    mux = ToolMux(registry=registry)

    result = run(
        mux.parallel(
            [
                {"tool": "ok", "arguments": {"value": "done"}},
                {"tool": "broken_tool", "arguments": {}},
                {"tool": "not_exists", "arguments": {}},
            ]
        )
    )

    assert result["status"] == "partial"
    assert result["succeeded"] == 1
    assert result["failed"] == 2
    assert result["failed_indexes"] == [1, 2]


def test_parallel_invalid_calls_are_wrapped() -> None:
    registry = ToolRegistry()
    registry.register("ok", lambda: "ok", read_only=True)
    mux = ToolMux(registry=registry)

    result = run(
        mux.parallel(
            [
                {"arguments": {}},
                "bad-call",
                {"tool": "ok", "arguments": "bad-args"},
            ]
        )
    )

    assert result["status"] == "partial"
    assert result["failed_indexes"] == [0, 1, 2]
    assert result["failed"] == 3


def test_read_only_cache_hit() -> None:
    registry = ToolRegistry()
    calls = {"count": 0}

    def search_fake(topic: str) -> dict[str, object]:
        calls["count"] += 1
        return {"topic": topic, "count": calls["count"]}

    registry.register("search_fake", search_fake, read_only=True)
    mux = ToolMux(registry=registry)

    first = run(mux.call("search_fake", {"topic": "agent"}))
    second = run(mux.call("search_fake", {"topic": "agent"}))

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["result"] == first["result"]
    assert mux.cache.stats()["hits"] >= 1


def test_mutating_tool_not_cached() -> None:
    registry = ToolRegistry()
    calls = {"count": 0}

    def accept_fake(paper_id: int) -> dict[str, int]:
        calls["count"] += 1
        return {"paper_id": paper_id, "count": calls["count"]}

    registry.register("accept_fake", accept_fake, read_only=False)
    mux = ToolMux(registry=registry)

    first = run(mux.call("accept_fake", {"paper_id": 1}))
    second = run(mux.call("accept_fake", {"paper_id": 1}))

    assert first["cached"] is False
    assert second["cached"] is False
    assert calls["count"] == 2


def test_batch_uses_parallel_semantics() -> None:
    registry = ToolRegistry()
    registry.register("get_fake", lambda value: {"value": value}, read_only=True)
    mux = ToolMux(registry=registry)

    result = run(mux.batch("get_fake", [{"value": 1}, {"value": 2}]))

    assert result["status"] == "completed"
    assert len(result["results"]) == 2
    assert result["failed_indexes"] == []
