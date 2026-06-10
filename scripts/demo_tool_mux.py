from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from pprint import pprint

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.tool_mux import ToolMux, ToolRegistry


def search_papers(topic: str, max_results: int = 5) -> list[dict[str, object]]:
    return [
        {
            "id": index + 1,
            "title": f"{topic} paper {index + 1}",
            "score": round(0.95 - index * 0.05, 2),
        }
        for index in range(max_results)
    ]


def list_accepted_papers() -> list[dict[str, object]]:
    return [
        {"id": 101, "title": "Accepted agent paper"},
        {"id": 102, "title": "Accepted retrieval paper"},
    ]


def accept_paper(paper_id: int) -> dict[str, object]:
    return {"paper_id": paper_id, "status": "accepted"}


def broken_tool() -> None:
    raise RuntimeError("demo failure from broken_tool")


async def main() -> None:
    registry = ToolRegistry()
    registry.register("search_papers", search_papers, "模拟搜索论文")
    registry.register("list_accepted_papers", list_accepted_papers, "模拟列出已接收论文")
    registry.register("accept_paper", accept_paper, "模拟接收论文")
    registry.register("broken_tool", broken_tool, "故意抛异常的工具", read_only=False)

    mux = ToolMux(registry=registry, max_concurrency=2)

    print("\n1. 单次 call")
    pprint(await mux.call("search_papers", {"topic": "LLM agent", "max_results": 2}))

    print("\n2. parallel 中部分失败")
    pprint(
        await mux.parallel(
            [
                {"tool": "search_papers", "arguments": {"topic": "RAG", "max_results": 1}},
                {"tool": "broken_tool", "arguments": {}},
                {"tool": "list_accepted_papers", "arguments": {}},
            ]
        )
    )

    print("\n3. batch 同一个工具多参数调用")
    pprint(
        await mux.batch(
            "search_papers",
            [
                {"topic": "agent memory", "max_results": 1},
                {"topic": "tool use", "max_results": 1},
            ],
        )
    )

    print("\n4. search_papers 第二次调用命中缓存")
    args = {"topic": "cache demo", "max_results": 1}
    pprint(await mux.call("search_papers", args))
    pprint(await mux.call("search_papers", {"max_results": 1, "topic": "cache demo"}))
    pprint(mux.cache.stats())

    print("\n5. accept_paper 不进入缓存")
    pprint(await mux.call("accept_paper", {"paper_id": 42}))
    pprint(await mux.call("accept_paper", {"paper_id": 42}))
    pprint(mux.cache.stats())


if __name__ == "__main__":
    asyncio.run(main())
