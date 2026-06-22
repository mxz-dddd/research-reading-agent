from app.agent.tool_registry import ToolRegistry as ResearchToolRegistry
from app.services.tool_mux import MuxToolRegistry, ToolCache, ToolMux


def build_research_tool_mux(
    *,
    ttl_seconds: int = 300,
    max_entries: int = 256,
    max_concurrency: int = 5,
) -> ToolMux:
    research_tools = ResearchToolRegistry()
    registry = MuxToolRegistry()

    registry.register(
        "search_papers",
        research_tools.search_papers,
        description="Search papers by topic and store search results",
        read_only=False,
    )
    registry.register(
        "list_accepted_papers",
        research_tools.list_accepted_papers,
        description="List accepted papers",
        read_only=True,
    )
    registry.register(
        "get_paper_detail",
        research_tools.get_paper_detail,
        description="Get paper detail by paper_id",
        read_only=True,
    )
    registry.register(
        "accept_paper",
        research_tools.accept_paper,
        description="Accept a paper into the reading list",
        read_only=False,
    )
    registry.register(
        "ingest_paper",
        research_tools.ingest_paper,
        description="Download and ingest a paper",
        read_only=False,
    )
    registry.register(
        "batch_ingest_papers",
        research_tools.batch_ingest_papers,
        description="Sequentially ingest a selected batch of papers",
        read_only=False,
    )
    registry.register(
        "generate_knowledge",
        research_tools.generate_knowledge,
        description="Generate knowledge tree from accepted papers",
        read_only=False,
    )
    registry.register(
        "generate_innovation",
        research_tools.generate_innovation,
        description="Generate innovation ideas from accepted papers and knowledge tree",
        read_only=False,
    )

    cache = ToolCache(ttl_seconds=ttl_seconds, max_entries=max_entries)
    return ToolMux(
        registry=registry,
        cache=cache,
        max_concurrency=max_concurrency,
    )
