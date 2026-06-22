from datetime import date
from urllib.error import URLError

from app.tools import search_papers as search_module
from app.tools.search_papers import (
    _build_arxiv_query,
    _build_arxiv_query_plans,
    _build_search_terms,
    search_papers,
)


def _paper(url: str, title: str = "VLF propagation delay", published_at: str = "2024-01-01"):
    return {
        "title": title,
        "authors": "A. Researcher",
        "abstract": "VLF propagation delay in the low ionosphere.",
        "url": url,
        "source": "arxiv",
        "published_at": published_at,
    }


def test_strict_query_with_results_does_not_execute_loose_query(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(query: str, limit: int):
        calls.append(query)
        return [_paper("https://arxiv.org/abs/2401.00001")]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)

    result = search_papers("VLF propagation delay correction", limit=1)

    assert len(result.papers) == 1
    assert len(calls) == 1
    assert result.query_level == 1


def test_second_level_returns_results_after_strict_zero(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(query: str, limit: int):
        calls.append(query)
        if len(calls) == 1:
            return []
        return [_paper("https://arxiv.org/abs/2401.00002")]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)

    result = search_papers("VLF propagation delay correction", limit=1)

    assert len(result.papers) == 1
    assert result.query_level == 2
    assert len(calls) == 2


def test_loose_query_returns_results_after_earlier_levels_zero(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(query: str, limit: int):
        calls.append(query)
        if len(calls) < 4:
            return []
        return [_paper("https://arxiv.org/abs/2401.00003")]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)

    result = search_papers("VLF propagation delay correction", limit=1)

    assert len(result.papers) == 1
    assert result.query_level == 4


def test_duplicate_papers_across_levels_are_deduped(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(query: str, limit: int):
        calls.append(query)
        if len(calls) == 1:
            return [_paper("https://arxiv.org/abs/2401.00004")]
        return [
            _paper("https://arxiv.org/abs/2401.00004"),
            _paper("https://arxiv.org/abs/2401.00005"),
        ]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)

    result = search_papers("VLF propagation delay correction", limit=2)

    assert [paper["url"] for paper in result.papers] == [
        "https://arxiv.org/abs/2401.00004",
        "https://arxiv.org/abs/2401.00005",
    ]


def test_reaching_limit_stops_following_queries(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(query: str, limit: int):
        calls.append(query)
        return [
            _paper("https://arxiv.org/abs/2401.00006"),
            _paper("https://arxiv.org/abs/2401.00007"),
        ]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)

    result = search_papers("VLF propagation delay correction", limit=2)

    assert len(result.papers) == 2
    assert len(calls) == 1


def test_keyword_processing_preserves_abbreviation_phrase_and_hyphenated_term() -> None:
    terms = _build_search_terms("VLF propagation delay Wait-Spies model research paper")

    assert "VLF" in terms.required_terms
    assert "propagation delay" in terms.phrases
    assert "Wait-Spies" in terms.phrases or "Wait-Spies" in terms.optional_terms
    assert "paper" not in terms.optional_terms
    assert "research" not in terms.optional_terms
    assert "all:VLF" in _build_arxiv_query("VLF propagation delay")
    assert 'all:"propagation delay"' in _build_arxiv_query("VLF propagation delay")


def test_date_range_is_added_to_arxiv_query() -> None:
    plans = _build_arxiv_query_plans(
        _build_search_terms("VLF propagation delay"),
        published_from=date(2016, 6, 17),
        published_to=date(2026, 6, 17),
    )

    assert plans[0].query.startswith("submittedDate:[201606170000 TO 202606172359]")


def test_date_filter_requests_extra_candidates_and_filters(monkeypatch) -> None:
    requested_limits: list[int] = []

    def fake_search(query: str, limit: int):
        requested_limits.append(limit)
        return [
            _paper("https://arxiv.org/abs/1501.00001", published_at="2015-01-01"),
            _paper("https://arxiv.org/abs/2401.00008", published_at="2024-01-01"),
        ]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)

    result = search_papers(
        "VLF propagation delay",
        limit=1,
        published_from=date(2020, 1, 1),
        published_to=date(2026, 6, 17),
    )

    assert requested_limits[0] == 30
    assert len(result.papers) == 1
    assert result.papers[0]["published_at"] == "2024-01-01"


def test_arxiv_network_failure_uses_mock_only_after_all_queries_fail(monkeypatch) -> None:
    def fail_search(query: str, limit: int):
        raise URLError("offline")

    monkeypatch.setattr(search_module, "_search_arxiv_query", fail_search)

    result = search_papers("VLF propagation delay correction", limit=1)

    assert result.source == "mock"
    assert len(result.papers) == 1
    assert result.attempted_queries


def test_excluded_first_batch_returns_next_batch_and_expands_candidates(monkeypatch) -> None:
    requested_limits: list[int] = []

    def fake_search(query: str, limit: int):
        requested_limits.append(limit)
        return [_paper(f"https://arxiv.org/abs/2401.{index:05d}") for index in range(1, 11)]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)
    excluded = [f"http://arxiv.org/pdf/2401.{index:05d}.pdf" for index in range(1, 6)]

    result = search_papers("VLF propagation delay", limit=5, exclude_urls=excluded)

    assert requested_limits[0] == 30
    assert [paper["url"] for paper in result.papers] == [
        f"https://arxiv.org/abs/2401.{index:05d}" for index in range(6, 11)
    ]


def test_excluded_arxiv_id_normalizes_abs_pdf_and_http_https(monkeypatch) -> None:
    def fake_search(query: str, limit: int):
        return [
            _paper("https://arxiv.org/pdf/2401.00001.pdf"),
            _paper("http://arxiv.org/abs/2401.00002"),
        ]

    monkeypatch.setattr(search_module, "_search_arxiv_query", fake_search)

    result = search_papers(
        "VLF propagation delay",
        limit=1,
        exclude_urls=["http://arxiv.org/abs/2401.00001"],
    )

    assert [paper["url"] for paper in result.papers] == ["http://arxiv.org/abs/2401.00002"]
