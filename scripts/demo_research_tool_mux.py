from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from pprint import pprint

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.tool_mux_factory import build_research_tool_mux


async def main() -> None:
    mux = build_research_tool_mux()

    print("\n1. Registry demo")
    tools = mux.registry.list_tools()
    pprint(tools)
    search_tool = next(tool for tool in tools if tool["name"] == "search_papers")
    print(
        "\nsearch_papers is registered as read_only=False because it stores search results."
    )
    pprint(search_tool)

    print("\n2. Safe parallel demo")
    result = await mux.parallel(
        [
            {"tool": "list_accepted_papers", "arguments": {}},
            {"tool": "not_exists", "arguments": {}},
        ]
    )

    print("\nParallel summary")
    pprint(
        {
            "status": result["status"],
            "succeeded": result["succeeded"],
            "failed": result["failed"],
            "failed_indexes": result["failed_indexes"],
        }
    )

    print("\nParallel results")
    pprint(result["results"])

    print("\n3. Cache demo")
    first = await mux.call("list_accepted_papers", {})
    second = await mux.call("list_accepted_papers", {})
    pprint(first)
    pprint(second)
    pprint(mux.cache.stats())


if __name__ == "__main__":
    asyncio.run(main())
