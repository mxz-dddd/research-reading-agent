from dataclasses import dataclass
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import certifi


ARXIV_API_URL = "https://export.arxiv.org/api/query"


@dataclass
class PaperSearchResult:
    papers: list[dict[str, Any]]
    source: str
    error: str | None = None


def search_papers(query: str, limit: int = 5) -> PaperSearchResult:
    try:
        papers = _search_arxiv(query=query, limit=limit)
        return PaperSearchResult(papers=papers, source="arxiv")
    except (HTTPError, URLError, TimeoutError) as exc:
        return PaperSearchResult(
            papers=_mock_papers(query=query, limit=limit),
            source="mock",
            error=f"arXiv 网络请求失败，已使用 mock fallback：{exc}",
        )
    except ET.ParseError as exc:
        return PaperSearchResult(
            papers=_mock_papers(query=query, limit=limit),
            source="mock",
            error=f"arXiv 返回内容解析失败，已使用 mock fallback：{exc}",
        )
    except ValueError as exc:
        return PaperSearchResult(
            papers=_mock_papers(query=query, limit=limit),
            source="mock",
            error=f"arXiv 返回数据异常，已使用 mock fallback：{exc}",
        )


def _search_arxiv(query: str, limit: int) -> list[dict[str, Any]]:
    params = urlencode(
        {
            "search_query": _build_arxiv_query(query),
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


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


def _build_arxiv_query(query: str) -> str:
    # arXiv 的 all:foo bar 查询会比较宽；拆成 AND 后更适合初筛。
    words = [word.strip() for word in query.replace("，", " ").replace(",", " ").split()]
    words = [word for word in words if word]
    if not words:
        return f"all:{query}"
    return " AND ".join(f"all:{word}" for word in words)


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())
