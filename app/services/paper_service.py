from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from app.core.config import settings
from app.core.exceptions import InvalidRequestError
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
from app.tools.search_papers import search_papers


class PaperService:
    def __init__(
        self,
        paper_repo: PaperRepository | None = None,
        archive_service: ArchiveService | None = None,
    ) -> None:
        self.paper_repo = paper_repo if paper_repo is not None else PaperRepository()
        self.archive_service = archive_service if archive_service is not None else ArchiveService()

    def search_and_store(self, payload: PaperSearchRequest) -> list[PaperRead]:
        topic = payload.search_topic.strip()
        if not topic:
            raise InvalidRequestError("topic 不能为空")

        search_result = search_papers(query=topic, limit=payload.result_limit)
        papers: list[PaperRead] = []
        for item in search_result.papers:
            screening = self._build_screening(topic=topic, paper=item)
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
                    topic=topic,
                    max_results=payload.result_limit,
                    error=search_result.error,
                ),
            )
        )
        return papers

    def list_papers(self, status: str | None = None) -> list[PaperRead]:
        return self.paper_repo.list_all(status=status)

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

    def _build_screening(self, topic: str, paper: dict[str, Any]) -> dict[str, Any]:
        if settings.openai_api_key:
            llm_result = self._try_llm_screening(topic=topic, paper=paper)
            if llm_result:
                return llm_result
        return self._rule_based_screening(topic=topic, paper=paper)

    def _try_llm_screening(self, topic: str, paper: dict[str, Any]) -> dict[str, Any] | None:
        prompt = f"""
你是科研论文助手。请根据用户研究主题和论文信息，输出适合中文快速初筛的 JSON。

研究主题：{topic}
论文标题：{paper.get("title")}
论文摘要：{paper.get("abstract")}

只返回 JSON，不要 Markdown。字段：
- screening_summary: 中文，2-4 句话，说明研究问题、方法/对象、可能价值
- relevance_score: 1-5 的整数，5 表示高度相关
- worth_reading: 只能是 "值得继续看"、"可选阅读"、"暂不优先" 之一
"""
        body = {
            "model": settings.openai_model,
            "input": prompt,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30, context=self._ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
            text = self._extract_response_text(data)
            parsed = json.loads(text)
            return self._normalize_screening(parsed)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            # LLM 失败不影响接口可用，直接回退到规则版初筛。
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

    def _rule_based_screening(self, topic: str, paper: dict[str, Any]) -> dict[str, Any]:
        title = str(paper.get("title") or "")
        abstract = str(paper.get("abstract") or "")
        text = f"{title} {abstract}".lower()
        topic_words = [word.lower() for word in topic.replace("，", " ").replace(",", " ").split()]
        matched = [word for word in topic_words if word and word in text]
        match_ratio = len(matched) / max(len(topic_words), 1)

        if topic.lower() in text:
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
            f"这篇论文与主题“{topic}”的初步相关度为 {score}/5。"
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
        topic: str,
        max_results: int,
        error: str | None = None,
    ) -> str:
        text = f"topic={topic}; max_results={max_results}"
        if error:
            text += f"; fallback_reason={error}"
        return text

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
        with open(path, encoding="utf-8") as f:
            text = f.read()
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
你是科研论文助手。请基于论文信息生成结构化中文深度总结。

阅读模式：{mode}
论文标题：{paper.title}
作者：{paper.authors}
发表时间：{paper.published_at}
论文链接：{paper.url}
文本内容：
{text[:12000]}

请用 Markdown 输出，必须包含这些小节：
## 研究问题
## 核心方法
## 关键贡献
## 实验/验证情况
## 优势
## 局限
## 对后续研究的启发
"""
        body = {"model": settings.openai_model, "input": prompt}
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=45, context=self._ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
            text_output = self._extract_response_text(data)
            return text_output.strip() or None
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
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
