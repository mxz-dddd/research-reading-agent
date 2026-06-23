import pytest

from app.agent.orchestrator import AgentOrchestrator


@pytest.fixture
def fallback_router() -> AgentOrchestrator:
    # _route_with_fallback only uses pure helper methods, so this avoids service,
    # repository, network, and database setup during routing tests.
    return AgentOrchestrator.__new__(AgentOrchestrator)


@pytest.mark.parametrize(
    ("message", "expected_intent", "expected_tool"),
    [
        ("你现在支持哪些能力", "help", "help"),
        (
            "搜索 large language model medical imaging 论文，给我 2 篇",
            "search_papers",
            "search_papers",
        ),
        ("接收第 2 篇论文", "accept_paper", "accept_paper"),
        ("对第 3 篇做深入阅读", "ingest_paper", "ingest_paper"),
        ("当前有哪些已接收论文", "list_accepted_papers", "list_accepted_papers"),
        ("查看 P12 详情", "get_paper_detail", "get_paper_detail"),
        ("根据当前已接收论文生成知识树", "generate_knowledge", "generate_knowledge"),
        ("根据当前已接收论文总结创新点", "generate_innovation", "generate_innovation"),
    ],
)
def test_fallback_routes_to_expected_tool(
    fallback_router: AgentOrchestrator,
    message: str,
    expected_intent: str,
    expected_tool: str,
) -> None:
    route = fallback_router._route_with_fallback(message)

    assert route["intent"] == expected_intent
    assert route["tool_name"] == expected_tool


def test_fallback_search_extracts_topic_and_limit(fallback_router: AgentOrchestrator) -> None:
    route = fallback_router._route_with_fallback(
        "搜索 large language model medical imaging 论文，给我 2 篇"
    )

    assert route["arguments"]["topic"] == "large language model medical imaging"
    assert route["arguments"]["max_results"] == 2


def test_fallback_accept_extracts_recent_result_ordinal(fallback_router: AgentOrchestrator) -> None:
    route = fallback_router._route_with_fallback("接收第 2 篇论文")

    assert route["arguments"] == {"ordinal": 2}


def test_fallback_ingest_extracts_recent_result_ordinal(fallback_router: AgentOrchestrator) -> None:
    route = fallback_router._route_with_fallback("对第 3 篇做深入阅读")

    assert route["arguments"] == {"ordinal": 3}


def test_fallback_detail_extracts_paper_id(fallback_router: AgentOrchestrator) -> None:
    route = fallback_router._route_with_fallback("查看 P12 详情")

    assert route["arguments"] == {"paper_id": 12}
