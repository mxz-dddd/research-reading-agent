from __future__ import annotations

import re
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

ARXIV_API_URL = "https://export.arxiv.org/api/query"
STOP_WORDS = {
    "paper",
    "papers",
    "research",
    "study",
    "studies",
    "related",
    "several",
    "recent",
    "search",
    "find",
    "about",
    "method",
    "methods",
}
OPTIONAL_WHEN_STRICT = {"correction", "corrected", "recent"}
KNOWN_ABBREVIATIONS = {"VLF", "PNT", "GPS", "RAG", "LLM", "LWPC", "GNSS", "SAR", "EEG"}
KNOWN_PHRASES = (
    "propagation delay",
    "phase delay",
    "group delay",
    "low ionosphere",
    "solar flare",
    "Wait-Spies",
)
VLF_SYNONYMS = (
    "propagation delay",
    "phase delay",
    "group delay",
    "propagation time",
    "phase perturbation",
    "ionosphere",
)


@dataclass
class PaperSearchResult:
    papers: list[dict[str, Any]]
    source: str
    error: str | None = None
    query_level: int | None = None
    effective_arxiv_query: str | None = None
    attempted_queries: list[dict[str, Any]] = field(default_factory=list)
    insufficient_results_within_date_range: bool = False


@dataclass(frozen=True)
class ArxivQueryPlan:
    level: int
    query: str
    description: str


@dataclass(frozen=True)
class SearchTerms:
    required_terms: tuple[str, ...]
    optional_terms: tuple[str, ...]
    phrases: tuple[str, ...]
    synonyms: tuple[str, ...]


def search_papers(
    query: str,
    limit: int = 5,
    *,
    required_terms: tuple[str, ...] = (),
    optional_terms: tuple[str, ...] = (),
    phrases: tuple[str, ...] = (),
    synonyms: tuple[str, ...] = (),
    published_from: date | None = None,
    published_to: date | None = None,
    exclude_urls: list[str] | None = None,
    exclude_arxiv_ids: list[str] | None = None,
) -> PaperSearchResult:
    excluded = _excluded_identities(exclude_urls or [], exclude_arxiv_ids or [])
    fetch_limit = (
        min(max(limit * 5 + len(excluded), 30), 100)
        if excluded or published_from or published_to
        else limit
    )
    terms = _build_search_terms(
        query,
        required_terms=required_terms,
        optional_terms=optional_terms,
        phrases=phrases,
        synonyms=synonyms,
    )
    plans = _build_arxiv_query_plans(
        terms, published_from=published_from, published_to=published_to
    )
    if not plans:
        return PaperSearchResult(
            papers=[],
            source="unavailable",
            error="无法形成有效英文检索词，请补充英文关键词后重试。",
        )
    attempted_queries: list[dict[str, Any]] = []
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []

    for plan in plans:
        try:
            papers = _search_arxiv_query(plan.query, fetch_limit)
            papers = _filter_by_published_date(
                papers,
                published_from=published_from,
                published_to=published_to,
            )
            added = 0
            for paper in papers:
                key = _paper_identity(paper)
                if not key or key in seen or key in excluded:
                    continue
                seen.add(key)
                paper["query_level"] = plan.level
                paper["effective_arxiv_query"] = plan.query
                collected.append(paper)
                added += 1
                if len(collected) >= limit:
                    break
            attempted_queries.append(
                {
                    "query_level": plan.level,
                    "effective_arxiv_query": plan.query,
                    "result_count": len(papers),
                    "added_count": added,
                    "success": True,
                }
            )
            if len(collected) >= limit:
                break
        except (HTTPError, URLError, TimeoutError, ET.ParseError, ValueError) as exc:
            errors.append(f"level {plan.level}: {type(exc).__name__}: {exc}")
            attempted_queries.append(
                {
                    "query_level": plan.level,
                    "effective_arxiv_query": plan.query,
                    "result_count": 0,
                    "added_count": 0,
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

    if collected:
        effective_query = collected[-1].get("effective_arxiv_query")
        query_level = int(collected[-1].get("query_level") or 0) or None
        return PaperSearchResult(
            papers=collected[:limit],
            source="arxiv",
            query_level=query_level,
            effective_arxiv_query=effective_query,
            attempted_queries=attempted_queries,
            insufficient_results_within_date_range=bool(
                (published_from or published_to) and len(collected) < limit
            ),
            error="; ".join(errors) if errors else None,
        )

    if errors and len(errors) == len(plans):
        mock_papers = [
            paper
            for paper in _mock_papers(query=query, limit=limit + len(excluded))
            if _paper_identity(paper) not in excluded
        ][:limit]
        return PaperSearchResult(
            papers=mock_papers,
            source="mock",
            error=f"arXiv 查询全部失败，已使用 mock fallback：{'; '.join(errors)}",
            query_level=None,
            effective_arxiv_query=None,
            attempted_queries=attempted_queries,
        )

    return PaperSearchResult(
        papers=[],
        source="arxiv",
        error="; ".join(errors) if errors else None,
        query_level=attempted_queries[-1]["query_level"] if attempted_queries else None,
        effective_arxiv_query=attempted_queries[-1]["effective_arxiv_query"]
        if attempted_queries
        else None,
        attempted_queries=attempted_queries,
        insufficient_results_within_date_range=bool(published_from or published_to),
    )


def _search_arxiv_query(arxiv_query: str, limit: int) -> list[dict[str, Any]]:
    params = urlencode(
        {
            "search_query": arxiv_query,
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    request = Request(
        f"{ARXIV_API_URL}?{params}",
        headers={"User-Agent": "research-agent/0.2"},
    )

    with urlopen(request, timeout=15, context=_ssl_context()) as response:
        raw_xml = response.read()

    root = ET.fromstring(raw_xml)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    papers: list[dict[str, Any]] = []

    for entry in entries:
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=ns))
        abstract = _clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
        url = _clean_text(entry.findtext("atom:id", default="", namespaces=ns))
        published_at = _clean_text(entry.findtext("atom:published", default="", namespaces=ns))
        authors = [
            _clean_text(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        authors = [author for author in authors if author]

        if not title or not url:
            raise ValueError("缺少论文标题或链接")

        papers.append(
            {
                "title": title,
                "authors": "; ".join(authors),
                "abstract": abstract,
                "url": url,
                "source": "arxiv",
                "published_at": published_at[:10] if published_at else None,
            }
        )

    return papers


def _mock_papers(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    fallback 数据只用于网络不可用或 arXiv 返回异常时，保证接口仍可演示。
    """
    mock_papers = [
        {
            "title": f"{query} 相关论文：方法综述",
            "authors": "Demo Author A; Demo Author B",
            "abstract": f"这是一条关于 {query} 的模拟摘要，用于验证论文搜索和入库流程。",
            "url": "https://example.com/paper-1",
            "source": "mock",
            "published_at": "2026-01-01",
            "summary": "模拟总结：适合用于初步了解该方向的研究背景。",
        },
        {
            "title": f"{query} 相关论文：最新进展",
            "authors": "Demo Author C",
            "abstract": f"这是一条关于 {query} 的第二条模拟摘要，用于验证多条论文结果。",
            "url": "https://example.com/paper-2",
            "source": "mock",
            "published_at": "2026-02-01",
            "summary": "模拟总结：适合用于追踪该方向的近期进展。",
        },
    ]
    return mock_papers[:limit]


def _build_search_terms(
    query: str,
    *,
    required_terms: tuple[str, ...] = (),
    optional_terms: tuple[str, ...] = (),
    phrases: tuple[str, ...] = (),
    synonyms: tuple[str, ...] = (),
) -> SearchTerms:
    extracted_phrases = list(phrases)
    lowered_query = query.lower()
    for phrase in KNOWN_PHRASES:
        if phrase.lower() in lowered_query and phrase not in extracted_phrases:
            extracted_phrases.append(phrase)

    tokens = _tokenize_query(query)
    required = list(required_terms)
    optional = list(optional_terms)
    for token in tokens:
        if token.upper() in KNOWN_ABBREVIATIONS:
            if token.upper() not in required:
                required.append(token.upper())
            continue
        if token.lower() in STOP_WORDS:
            continue
        if token.lower() in OPTIONAL_WHEN_STRICT:
            optional.append(token)
            continue
        if token not in optional and not _term_covered_by_phrase(token, extracted_phrases):
            optional.append(token)

    if not required and optional:
        required.append(optional.pop(0))

    normalized_required = _unique_terms(required)
    normalized_optional = _unique_terms(optional)
    normalized_phrases = _unique_terms(extracted_phrases)
    normalized_synonyms = _unique_terms(synonyms)
    if "VLF" in normalized_required:
        normalized_synonyms = _unique_terms((*normalized_synonyms, *VLF_SYNONYMS))

    return SearchTerms(
        required_terms=normalized_required,
        optional_terms=normalized_optional,
        phrases=normalized_phrases,
        synonyms=normalized_synonyms,
    )


def _build_arxiv_query_plans(
    terms: SearchTerms,
    *,
    published_from: date | None = None,
    published_to: date | None = None,
) -> list[ArxivQueryPlan]:
    required_parts = [_field_term(term) for term in terms.required_terms]
    optional_parts = [_field_term(term) for term in terms.optional_terms]
    phrase_parts = [_field_term(phrase) for phrase in terms.phrases]
    synonym_parts = [_field_term(term) for term in terms.synonyms]
    plans: list[ArxivQueryPlan] = []

    strict_parts = [*required_parts, *phrase_parts, *optional_parts]
    if strict_parts:
        plans.append(
            ArxivQueryPlan(
                1,
                _with_date_range(" AND ".join(strict_parts), published_from, published_to),
                "strict",
            )
        )

    if required_parts and optional_parts:
        plans.append(
            ArxivQueryPlan(
                2,
                _with_date_range(
                    " AND ".join([*required_parts, _or_group(optional_parts)]),
                    published_from,
                    published_to,
                ),
                "required plus optional",
            )
        )

    expanded = _unique_query_parts([*phrase_parts, *synonym_parts])
    if required_parts and expanded:
        plans.append(
            ArxivQueryPlan(
                3,
                _with_date_range(
                    " AND ".join([*required_parts, _or_group(expanded)]),
                    published_from,
                    published_to,
                ),
                "synonym expansion",
            )
        )

    loose = _unique_query_parts([*optional_parts[:3], *synonym_parts[:3]])
    if required_parts and loose:
        plans.append(
            ArxivQueryPlan(
                4,
                _with_date_range(
                    " AND ".join([required_parts[0], _or_group(loose)]),
                    published_from,
                    published_to,
                ),
                "loose fallback",
            )
        )

    if not plans:
        raw_query = _field_term(" ".join(terms.optional_terms))
        if raw_query:
            plans.append(
                ArxivQueryPlan(
                    1,
                    _with_date_range(raw_query, published_from, published_to),
                    "raw",
                )
            )

    return _dedupe_plans(plans)


def _build_arxiv_query(query: str) -> str:
    plans = _build_arxiv_query_plans(_build_search_terms(query))
    if not plans:
        raise ValueError("无法形成有效英文检索词")
    return plans[0].query


def _tokenize_query(query: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*|\d+(?:\.\d+)?", query)


def _field_term(term: str) -> str:
    cleaned = _clean_query_term(term)
    if not cleaned:
        return ""
    if " " in cleaned or "-" in cleaned:
        return f'all:"{cleaned}"'
    return f"all:{cleaned}"


def _clean_query_term(term: str) -> str:
    return str(term or "").strip().strip("'\"“”‘’")


def _or_group(parts: list[str]) -> str:
    non_empty = [part for part in parts if part]
    if len(non_empty) == 1:
        return non_empty[0]
    return "(" + " OR ".join(non_empty) + ")"


def _with_date_range(query: str, published_from: date | None, published_to: date | None) -> str:
    if not published_from and not published_to:
        return query
    start = (published_from or date(1991, 1, 1)).strftime("%Y%m%d") + "0000"
    end = (published_to or date.today()).strftime("%Y%m%d") + "2359"
    date_query = f"submittedDate:[{start} TO {end}]"
    return f"{date_query} AND ({query})"


def _filter_by_published_date(
    papers: list[dict[str, Any]],
    *,
    published_from: date | None,
    published_to: date | None,
) -> list[dict[str, Any]]:
    if not published_from and not published_to:
        return papers
    filtered: list[dict[str, Any]] = []
    for paper in papers:
        published = _parse_date(paper.get("published_at"))
        if published is None:
            continue
        if published_from and published < published_from:
            continue
        if published_to and published > published_to:
            continue
        filtered.append(paper)
    return filtered


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _paper_identity(paper: dict[str, Any]) -> str | None:
    url = str(paper.get("url") or "").strip()
    if not url:
        return None
    return _arxiv_id_from_url(url) or _normalize_url(url)


def _arxiv_id_from_url(url: str) -> str | None:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", url, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).removesuffix(".pdf").lower()


def _normalize_url(url: str) -> str:
    return str(url or "").strip().lower().replace("http://", "https://").rstrip("/")


def _excluded_identities(urls: list[str], arxiv_ids: list[str]) -> set[str]:
    identities = {str(value).strip().lower().removesuffix(".pdf") for value in arxiv_ids if value}
    for url in urls:
        identity = _arxiv_id_from_url(url) or _normalize_url(url)
        if identity:
            identities.add(identity)
    return identities


def _unique_terms(terms: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        cleaned = _clean_query_term(term)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def _unique_query_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        if not part:
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(part)
    return result


def _dedupe_plans(plans: list[ArxivQueryPlan]) -> list[ArxivQueryPlan]:
    seen: set[str] = set()
    result: list[ArxivQueryPlan] = []
    for plan in plans:
        if plan.query in seen:
            continue
        seen.add(plan.query)
        result.append(plan)
    return result


def _term_covered_by_phrase(term: str, phrases: list[str]) -> bool:
    lower = term.lower()
    return any(lower in phrase.lower().split() for phrase in phrases)


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())
