from __future__ import annotations

from app.core.exceptions import InvalidRequestError

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from app.core.config import settings
from app.repositories.knowledge_repo import KnowledgeRepository
from app.repositories.paper_repo import PaperRepository
from app.schemas.knowledge import (
    KnowledgeArtifactCreate,
    KnowledgeArtifactRead,
    KnowledgeGenerateRequest,
)
from app.schemas.paper import PaperRead
from app.services.archive_service import ArchiveService
from app.tools.build_tree import CATEGORIES, paper_label, pick_category


class KnowledgeService:
    def __init__(self) -> None:
        self.paper_repo = PaperRepository()
        self.knowledge_repo = KnowledgeRepository()
        self.archive_service = ArchiveService()

    def generate(self, payload: KnowledgeGenerateRequest) -> KnowledgeArtifactRead:
        papers = self._select_papers(payload.topic)
        if len(papers) < 2:
            raise InvalidRequestError("至少需要 2 篇已接收论文才能生成知识树。请先搜索、接收并尽量 ingest 更多论文。")

        artifact_data = self._build_with_llm(payload.topic, papers)
        generation_method = "llm"
        if artifact_data is None:
            artifact_data = self._build_fallback(payload.topic, papers)
            generation_method = "fallback"

        markdown = self._compose_archive_markdown(
            topic=payload.topic,
            source_paper_count=len(papers),
            generation_method=generation_method,
            artifact_data=artifact_data,
        )
        local_path = self.archive_service.write_knowledge_artifact(payload.topic, markdown)

        return self.knowledge_repo.create(
            KnowledgeArtifactCreate(
                topic=payload.topic,
                source_paper_count=len(papers),
                knowledge_tree_markdown=artifact_data["knowledge_tree_markdown"],
                learning_roadmap_markdown=artifact_data["learning_roadmap_markdown"],
                mermaid_mindmap=artifact_data["mermaid_mindmap"],
                mermaid_flowchart=artifact_data["mermaid_flowchart"],
                local_markdown_path=local_path,
                generation_method=generation_method,
            )
        )

    def latest(self) -> KnowledgeArtifactRead:
        return self.knowledge_repo.latest()

    def history(self) -> list[KnowledgeArtifactRead]:
        return self.knowledge_repo.list()

    def _select_papers(self, topic: str | None) -> list[PaperRead]:
        papers = self.paper_repo.list_accepted()
        if not topic:
            return papers
        topic_lower = topic.lower()
        filtered = []
        for paper in papers:
            text = " ".join(
                [
                    paper.title or "",
                    paper.abstract or "",
                    paper.deep_summary or "",
                    paper.screening_summary or "",
                ]
            ).lower()
            if topic_lower in text:
                filtered.append(paper)
        return filtered

    def _build_with_llm(self, topic: str | None, papers: list[PaperRead]) -> dict[str, str] | None:
        if not settings.openai_api_key:
            return None

        prompt = self._build_llm_prompt(topic, papers)
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
            with urlopen(request, timeout=60, context=self._ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(self._extract_response_text(data))
            return self._normalize_artifact_data(parsed)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _build_llm_prompt(self, topic: str | None, papers: list[PaperRead]) -> str:
        paper_blocks = []
        for paper in papers:
            paper_blocks.append(
                f"""
paper_id: {paper.id}
title: {paper.title}
worth_reading: {paper.worth_reading}
relevance_score: {paper.relevance_score}
screening_summary: {paper.screening_summary}
deep_summary: {(paper.deep_summary or paper.abstract or "")[:3000]}
"""
            )

        return f"""
你是科研学习规划助手。请基于已接收并归档的论文，生成中文知识树和学习路径。

主题：{topic or "全部已接收论文"}

要求：
1. 明确区分“来自论文内容的归纳”和“基于模型的组织与推断”。
2. 尽量把论文归入：背景与综述、核心问题定义、关键方法、实验与验证、应用与扩展、局限与开放问题。
3. 每个节点尽量关联 paper_id 或标题。
4. 输出 JSON，不要 Markdown 包裹代码块。

JSON 字段：
- knowledge_tree_markdown
- learning_roadmap_markdown
- mermaid_mindmap
- mermaid_flowchart

论文材料：
{chr(10).join(paper_blocks)}
"""

    def _build_fallback(self, topic: str | None, papers: list[PaperRead]) -> dict[str, str]:
        grouped: dict[str, list[PaperRead]] = {category: [] for category in CATEGORIES}
        for paper in papers:
            grouped[pick_category(paper)].append(paper)

        tree_lines = [
            f"# 知识树：{topic or '全部已接收论文'}",
            "",
            "## 来自论文内容的归纳",
        ]
        for category in CATEGORIES:
            tree_lines.append(f"### {category}")
            category_papers = grouped[category] or papers[:1]
            for paper in category_papers:
                summary = paper.deep_summary or paper.screening_summary or paper.abstract or "暂无摘要"
                tree_lines.append(f"- {paper_label(paper)}：{summary[:180]}...")
            tree_lines.append("")
        tree_lines.extend(
            [
                "## 基于模型的组织与推断",
                "- 当前为规则版 fallback：系统根据标题、摘要、初筛和深度总结中的关键词进行粗分类。",
                "- TODO: 后续可用 LLM 或更细的章节解析提升分类质量。",
            ]
        )

        sorted_papers = sorted(
            papers,
            key=lambda paper: (paper.relevance_score or 0, paper.worth_reading == "值得继续看"),
            reverse=True,
        )
        roadmap_lines = [
            f"# 学习路径：{topic or '全部已接收论文'}",
            "",
            "## 1. 先打基础",
            *[f"- {paper_label(paper)}" for paper in sorted_papers[:2]],
            "",
            "## 2. 再理解核心方法",
            *[f"- {paper_label(paper)}" for paper in sorted_papers[1:3] or sorted_papers[:1]],
            "",
            "## 3. 再看实验与扩展",
            *[f"- {paper_label(paper)}" for paper in sorted_papers[2:4] or sorted_papers[-1:]],
            "",
            "## 4. 最后关注开放问题",
            "- 对比各论文 deep_summary 中的“局限”和“对后续研究的启发”。",
            "- 重点记录方法假设、实验边界和是否能迁移到你的研究方向。",
            "",
            "## 来源说明",
            "- 论文排序来自 relevance_score、worth_reading 和规则版组织推断。",
        ]

        mindmap_lines = ["mindmap", f"  root(({topic or '知识树'}))"]
        for category in CATEGORIES:
            mindmap_lines.append(f"    {category}")
            for paper in (grouped[category] or [])[:4]:
                mindmap_lines.append(f"      P{paper.id} {self._short_title(paper.title)}")

        flow_lines = ["flowchart TD", "  A[先读背景与综述] --> B[理解核心问题]", "  B --> C[学习关键方法]", "  C --> D[检查实验与验证]", "  D --> E[应用扩展与开放问题]"]
        for paper in sorted_papers[:6]:
            flow_lines.append(f"  P{paper.id}[P{paper.id} {self._short_title(paper.title)}] --> C")

        return {
            "knowledge_tree_markdown": "\n".join(tree_lines),
            "learning_roadmap_markdown": "\n".join(roadmap_lines),
            "mermaid_mindmap": "\n".join(mindmap_lines),
            "mermaid_flowchart": "\n".join(flow_lines),
        }

    def _normalize_artifact_data(self, data: dict[str, Any]) -> dict[str, str]:
        required = [
            "knowledge_tree_markdown",
            "learning_roadmap_markdown",
            "mermaid_mindmap",
            "mermaid_flowchart",
        ]
        normalized = {key: str(data.get(key, "")).strip() for key in required}
        if not all(normalized.values()):
            raise ValueError("LLM 知识树结果缺少必要字段")
        return normalized

    def _compose_archive_markdown(
        self,
        *,
        topic: str | None,
        source_paper_count: int,
        generation_method: str,
        artifact_data: dict[str, str],
    ) -> str:
        return f"""# 知识树归档：{topic or '全部已接收论文'}

- 来源论文数：{source_paper_count}
- 生成方式：{generation_method}

{artifact_data["knowledge_tree_markdown"]}

---

{artifact_data["learning_roadmap_markdown"]}

---

## Mermaid Mindmap

```mermaid
{artifact_data["mermaid_mindmap"]}
```

## Mermaid Flowchart

```mermaid
{artifact_data["mermaid_flowchart"]}
```
"""

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        if data.get("output_text"):
            return str(data["output_text"]).strip()
        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    parts.append(str(content.get("text", "")))
        return "".join(parts).strip()

    def _short_title(self, title: str, max_len: int = 42) -> str:
        return title if len(title) <= max_len else title[:max_len] + "..."

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())
