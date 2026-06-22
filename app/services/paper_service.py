import json
import re
import ssl
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from fastapi import HTTPException

from app.core.config import settings
from app.core.llm_client import LLMClientError, OpenAICompatibleClient
from app.repositories.paper_repo import PaperRepository
from app.schemas.paper import (
    PaperAcceptRequest,
    PaperCreate,
    PaperIngestRequest,
    PaperRead,
    PaperSearchHistoryCreate,
    PaperSearchHistoryRead,
    PaperSearchRequest,
)
from app.services.archive_service import ArchiveService
from app.services.search_query_translation_service import SearchQueryTranslationService
from app.tools.search_papers import search_papers


class PaperService:
    def __init__(self) -> None:
        self.paper_repo = PaperRepository()
        self.archive_service = ArchiveService()
        self.query_translation_service = SearchQueryTranslationService()

    def search_and_store(self, payload: PaperSearchRequest) -> list[PaperRead]:
        topic = payload.search_topic.strip()
        if not topic:
            raise HTTPException(status_code=400, detail="topic 不能为空")

        published_from, published_to = self._payload_or_text_date_range(payload, topic)
        academic_topic = self._strip_search_constraints(topic) or topic
        translation = self.query_translation_service.translate_for_search(academic_topic)
        effective_search_query = translation.search_query
        exclude_urls = self._excluded_urls(payload)
        search_result = search_papers(
            query=effective_search_query,
            limit=payload.result_limit,
            required_terms=translation.required_terms,
            optional_terms=translation.optional_terms,
            phrases=translation.phrases,
            synonyms=translation.synonyms,
            published_from=published_from,
            published_to=published_to,
            exclude_urls=exclude_urls,
            exclude_arxiv_ids=payload.exclude_arxiv_ids,
        )
        papers: list[PaperRead] = []
        for item in search_result.papers:
            existing = self._get_existing_paper(item.get("url"))
            if existing is not None:
                papers.append(existing)
                continue
            screening = self._build_screening(
                original_topic=topic,
                effective_search_query=effective_search_query,
                paper=item,
            )
            papers.append(
                self.paper_repo.create(
                    PaperCreate(
                        topic_id=payload.topic_id,
                        title=item["title"],
                        authors=item.get("authors"),
                        abstract=item.get("abstract"),
                        url=item.get("url"),
                        source=item.get("source"),
                        published_at=item.get("published_at"),
                        summary=screening["screening_summary"],
                        screening_summary=screening["screening_summary"],
                        relevance_score=screening["relevance_score"],
                        worth_reading=screening["worth_reading"],
                    )
                )
            )
        self.paper_repo.create_search_history(
            PaperSearchHistoryCreate(
                topic=topic,
                source=search_result.source,
                result_count=len(papers),
                query_text=self._build_history_text(
                    original_query=topic,
                    effective_search_query=effective_search_query,
                    was_translated=translation.was_translated,
                    translation_method=translation.translation_method,
                    query_level=search_result.query_level,
                    final_arxiv_query=search_result.effective_arxiv_query,
                    attempted_queries=search_result.attempted_queries,
                    published_from=published_from,
                    published_to=published_to,
                    insufficient_results_within_date_range=search_result.insufficient_results_within_date_range,
                    max_results=payload.result_limit,
                    error=search_result.error,
                ),
            )
        )
        return papers

    def _excluded_urls(self, payload: PaperSearchRequest) -> list[str]:
        urls = [url for url in payload.exclude_urls if url]
        for paper_id in payload.exclude_paper_ids:
            try:
                paper = self.paper_repo.get(paper_id)
            except HTTPException:
                continue
            if paper.url:
                urls.append(paper.url)
        return urls

    def list_papers(self, status: str | None = None) -> list[PaperRead]:
        return self.paper_repo.list(status=status)

    def list_search_history(self) -> list[PaperSearchHistoryRead]:
        return self.paper_repo.list_search_history()

    def get_paper(self, paper_id: int) -> PaperRead:
        return self.paper_repo.get(paper_id)

    def list_accepted(self) -> list[PaperRead]:
        return self.paper_repo.list_accepted()

    def save_paper(self, paper_id: int) -> PaperRead:
        return self.paper_repo.update_status(paper_id=paper_id, status="saved")

    def accept_paper(self, payload: PaperAcceptRequest) -> PaperRead:
        if payload.paper_id is not None:
            paper = self.paper_repo.get(payload.paper_id)
        else:
            paper = self.paper_repo.get_by_url(payload.url or "")
            if paper is None:
                # URL 直接接收时，先创建一条最小论文记录，后续 ingest 再补充内容。
                paper = self.paper_repo.create(
                    PaperCreate(
                        title=payload.url or "未命名论文",
                        url=payload.url,
                        source="manual",
                        status="found",
                    )
                )

        pdf_url = self._guess_pdf_url(paper.url)
        return self.paper_repo.accept(paper_id=paper.id, pdf_url=pdf_url)

    def ingest_paper(self, payload: PaperIngestRequest) -> PaperRead:
        paper = self.paper_repo.get(payload.paper_id)
        if not paper.is_accepted:
            paper = self.paper_repo.accept(paper_id=paper.id, pdf_url=self._guess_pdf_url(paper.url))

        base_name = self.archive_service.make_base_name(paper.id, paper.title)
        pdf_url = paper.pdf_url or self._guess_pdf_url(paper.url)
        local_pdf_path: str | None = None
        local_text_path: str | None = None
        download_error: str | None = None
        extract_error: str | None = None

        if pdf_url:
            local_pdf_path, download_error = self.archive_service.download_pdf(pdf_url, base_name)
            if local_pdf_path:
                local_text_path, extract_error = self.archive_service.extract_pdf_text(
                    local_pdf_path,
                    base_name,
                )

        text_for_summary = ""
        ingest_status = "abstract_only"
        if local_text_path:
            try:
                text_for_summary = self._read_text_preview(local_text_path)
                ingest_status = "pdf_text"
            except OSError as exc:
                extract_error = f"本地文本读取失败，已降级 abstract-only：{exc}"

        if not text_for_summary:
            text_for_summary = paper.abstract or "暂无摘要。"
            local_text_path = self.archive_service.write_abstract_text(text_for_summary, base_name)

        abstract_summary = self._build_abstract_summary(paper)
        deep_summary = self._build_deep_summary(
            paper=paper,
            text=text_for_summary,
            mode=ingest_status,
            download_error=download_error,
            extract_error=extract_error,
        )
        local_summary_path = self.archive_service.write_summary(deep_summary, base_name)

        return self.paper_repo.update_ingest_result(
            paper_id=paper.id,
            pdf_url=pdf_url,
            local_pdf_path=local_pdf_path,
            local_text_path=local_text_path,
            local_summary_path=local_summary_path,
            abstract_summary=abstract_summary,
            deep_summary=deep_summary,
            ingest_status=ingest_status,
        )

    def _build_screening(
        self,
        *,
        original_topic: str,
        effective_search_query: str,
        paper: dict[str, Any],
    ) -> dict[str, Any]:
        if settings.openai_api_key:
            llm_result = self._try_llm_screening(
                original_topic=original_topic,
                effective_search_query=effective_search_query,
                paper=paper,
            )
            if llm_result:
                return llm_result
        return self._rule_based_screening(
            original_topic=original_topic,
            effective_search_query=effective_search_query,
            paper=paper,
        )

    def _try_llm_screening(
        self,
        *,
        original_topic: str,
        effective_search_query: str,
        paper: dict[str, Any],
    ) -> dict[str, Any] | None:
        prompt = f"""
You are a research paper screening assistant. Based on the user topic, the actual English
search query, and paper metadata, return a Chinese JSON object for quick screening.

Original user topic: {original_topic}
Effective English search query: {effective_search_query}
Title: {paper.get("title")}
Abstract: {paper.get("abstract")}

Return JSON only, with these fields:
- screening_summary: Chinese, 2-4 sentences.
- relevance_score: integer 1-5.
- worth_reading: one of "值得继续看", "可选阅读", "暂不优先".
"""
        try:
            text = OpenAICompatibleClient().responses_text(
                prompt,
                instructions="Return only valid JSON for research paper screening.",
            )
            parsed = json.loads(text)
            return self._normalize_screening(parsed)
        except (LLMClientError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"paper screening LLM fallback: {type(exc).__name__}: {exc}")
            return None

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        if data.get("output_text"):
            return str(data["output_text"]).strip()

        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    parts.append(str(content.get("text", "")))
        return "".join(parts).strip()

    def _normalize_screening(self, data: dict[str, Any]) -> dict[str, Any]:
        worth_reading = data.get("worth_reading")
        if worth_reading not in {"值得继续看", "可选阅读", "暂不优先"}:
            worth_reading = "可选阅读"
        score = int(data.get("relevance_score", 3))
        score = max(1, min(5, score))
        summary = str(data.get("screening_summary", "")).strip()
        if not summary:
            raise ValueError("LLM 初筛结果缺少 screening_summary")
        return {
            "screening_summary": summary,
            "relevance_score": score,
            "worth_reading": worth_reading,
        }

    def _rule_based_screening(
        self,
        *,
        original_topic: str,
        effective_search_query: str,
        paper: dict[str, Any],
    ) -> dict[str, Any]:
        title = str(paper.get("title") or "")
        abstract = str(paper.get("abstract") or "")
        text = f"{title} {abstract}".lower()
        query_words = [
            word.lower()
            for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", effective_search_query)
        ]
        matched = [word for word in query_words if word and word in text]
        match_ratio = len(matched) / max(len(query_words), 1)

        if effective_search_query.lower() in text:
            score = 5
        elif match_ratio >= 0.6:
            score = 4
        elif match_ratio >= 0.3:
            score = 3
        else:
            score = 2

        if score >= 4:
            worth_reading = "值得继续看"
        elif score == 3:
            worth_reading = "可选阅读"
        else:
            worth_reading = "暂不优先"

        abstract_preview = abstract[:180] + ("..." if len(abstract) > 180 else "")
        summary = (
            f"这篇论文与主题“{original_topic}”的初步相关度为 {score}/5。"
            f"标题显示其关注点是“{title}”。"
        )
        if abstract_preview:
            summary += f" 摘要要点：{abstract_preview}"
        summary += f" 初筛建议：{worth_reading}。"

        return {
            "screening_summary": summary,
            "relevance_score": score,
            "worth_reading": worth_reading,
        }

    def _build_history_text(
        self,
        *,
        original_query: str,
        effective_search_query: str,
        was_translated: bool,
        translation_method: str,
        query_level: int | None,
        final_arxiv_query: str | None,
        attempted_queries: list[dict[str, Any]],
        published_from: date | None,
        published_to: date | None,
        insufficient_results_within_date_range: bool,
        max_results: int,
        error: str | None = None,
    ) -> str:
        text = (
            f"original_query={original_query}; "
            f"effective_search_query={effective_search_query}; "
            f"was_translated={str(was_translated).lower()}; "
            f"translation_method={translation_method}; "
            f"query_level={query_level}; "
            f"final_arxiv_query={final_arxiv_query}; "
            f"attempted_query_count={len(attempted_queries)}; "
            f"published_from={published_from}; "
            f"published_to={published_to}; "
            f"insufficient_results_within_date_range={str(insufficient_results_within_date_range).lower()}; "
            f"max_results={max_results}"
        )
        if error:
            text += f"; fallback_reason={error}"
        return text

    def _get_existing_paper(self, url: str | None) -> PaperRead | None:
        if not url or not hasattr(self.paper_repo, "get_by_url"):
            return None
        candidates = [url]
        if url.startswith("http://"):
            candidates.append("https://" + url.removeprefix("http://"))
        elif url.startswith("https://"):
            candidates.append("http://" + url.removeprefix("https://"))
        for candidate in candidates:
            paper = self.paper_repo.get_by_url(candidate)
            if paper is not None:
                return paper
        return None

    def _extract_published_range(self, text: str) -> tuple[date | None, date | None]:
        today = date.today()
        compact = re.sub(r"\s+", "", text)

        year_span = re.search(r"((?:19|20)\d{2})年?(?:到|至|-|~)((?:19|20)\d{2})年?", compact)
        if year_span:
            start_year = int(year_span.group(1))
            end_year = int(year_span.group(2))
            return date(start_year, 1, 1), date(end_year, 12, 31)

        since_year = re.search(r"((?:19|20)\d{2})年?以来", compact)
        if since_year:
            return date(int(since_year.group(1)), 1, 1), today

        recent_years = re.search(r"(?:近|最近)([一二两三四五六七八九十\d]+)年", compact)
        if recent_years:
            years = self._parse_year_count(recent_years.group(1))
            if years:
                return date(today.year - years, today.month, today.day), today

        return None, None

    def _strip_search_constraints(self, text: str) -> str:
        cleaned = re.sub(r"(?:近|最近)\s*[一二两三四五六七八九十\d]+\s*年", " ", text)
        cleaned = re.sub(r"(?:19|20)\d{2}\s*年?\s*以来", " ", cleaned)
        cleaned = re.sub(r"(?:19|20)\d{2}\s*年?\s*(?:到|至|-|~)\s*(?:19|20)\d{2}\s*年?", " ", cleaned)
        cleaned = re.sub(r"\d+\s*篇", " ", cleaned)
        cleaned = re.sub(r"(帮我|请|搜索|查找|找|论文|paper|papers|search|给我|几篇|相关的|相关|要|的)", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"[，,。.!！?？]", " ", cleaned)
        return " ".join(cleaned.split())

    def _parse_year_count(self, value: str) -> int | None:
        if value.isdigit():
            return int(value)
        chinese_numbers = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        if value == "十":
            return 10
        if value.startswith("十") and len(value) == 2:
            return 10 + chinese_numbers.get(value[1], 0)
        if value.endswith("十") and len(value) == 2:
            return chinese_numbers.get(value[0], 0) * 10
        if len(value) == 3 and value[1] == "十":
            return chinese_numbers.get(value[0], 0) * 10 + chinese_numbers.get(value[2], 0)
        return chinese_numbers.get(value)

    def _payload_or_text_date_range(
        self,
        payload: PaperSearchRequest,
        topic: str,
    ) -> tuple[date | None, date | None]:
        parsed_from = self._parse_date_value(payload.published_from)
        parsed_to = self._parse_date_value(payload.published_to)
        if parsed_from or parsed_to:
            return parsed_from, parsed_to
        return self._extract_published_range(topic)

    def _parse_date_value(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())

    def _guess_pdf_url(self, url: str | None) -> str | None:
        if not url:
            return None
        if url.endswith(".pdf") or "/pdf/" in url:
            return url
        if "arxiv.org/abs/" in url:
            paper_code = url.rstrip("/").split("/abs/")[-1]
            return f"https://arxiv.org/pdf/{paper_code}.pdf"
        return None

    def _read_text_preview(self, path: str, max_chars: int = 12000) -> str:
        text = open(path, encoding="utf-8").read()
        return text[:max_chars]

    def _build_abstract_summary(self, paper: PaperRead) -> str:
        abstract = paper.abstract or "暂无摘要"
        preview = abstract[:500] + ("..." if len(abstract) > 500 else "")
        return f"《{paper.title}》摘要概括：{preview}"

    def _build_deep_summary(
        self,
        *,
        paper: PaperRead,
        text: str,
        mode: str,
        download_error: str | None,
        extract_error: str | None,
    ) -> str:
        if settings.openai_api_key:
            llm_summary = self._try_llm_deep_summary(paper=paper, text=text, mode=mode)
            if llm_summary:
                return self._append_ingest_notes(llm_summary, mode, download_error, extract_error)

        fallback = self._rule_based_deep_summary(paper=paper, text=text, mode=mode)
        return self._append_ingest_notes(fallback, mode, download_error, extract_error)

    def _try_llm_deep_summary(self, paper: PaperRead, text: str, mode: str) -> str | None:
        prompt = f"""
You are a research paper reading assistant. Generate a structured Chinese Markdown deep summary.

Reading mode: {mode}
Title: {paper.title}
Authors: {paper.authors}
Published at: {paper.published_at}
URL: {paper.url}
Text:
{text[:12000]}

The Markdown must include these sections:
## 研究问题
## 核心方法
## 关键贡献
## 实验/验证情况
## 优势
## 局限
## 对后续研究的启发
"""
        try:
            text_output = OpenAICompatibleClient().responses_text(
                prompt,
                instructions=(
                    "You are a research paper reading assistant. Write a structured "
                    "Chinese Markdown deep summary."
                ),
            )
            return text_output.strip() or None
        except (LLMClientError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"paper summary LLM fallback: {type(exc).__name__}: {exc}")
            return None
    def _rule_based_deep_summary(self, paper: PaperRead, text: str, mode: str) -> str:
        preview = text[:900] + ("..." if len(text) > 900 else "")
        return f"""# {paper.title}

## 研究问题
当前为规则版总结，主要基于论文摘要或已提取文本判断。论文可能关注的问题可从标题和摘要中进一步确认。

## 核心方法
摘要/正文片段显示：{preview}

## 关键贡献
待人工阅读全文后确认。当前可先根据初筛结果和摘要判断其是否与研究方向相关。

## 实验/验证情况
规则版 fallback 暂不能可靠提取实验设置、数据集和指标。TODO: 后续增强 PDF 结构化解析。

## 优势
已完成基础归档，后续可以围绕方法、实验和结论继续精读。

## 局限
当前总结模式为 {mode}。如果是 abstract_only，信息量有限，不适合直接作为最终论文理解。

## 对后续研究的启发
建议下一步重点查看方法设计、实验对比、局限讨论，以及是否能迁移到你的研究问题。
"""

    def _append_ingest_notes(
        self,
        summary: str,
        mode: str,
        download_error: str | None,
        extract_error: str | None,
    ) -> str:
        notes = [summary.rstrip(), "", "## 归档状态", f"- 阅读模式：{mode}"]
        if download_error:
            notes.append(f"- PDF 下载提示：{download_error}")
        if extract_error:
            notes.append(f"- 文本提取提示：{extract_error}")
        return "\n".join(notes) + "\n"

