import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from fastapi import HTTPException

from app.core.config import settings
from app.repositories.innovation_repo import InnovationRepository
from app.repositories.knowledge_repo import KnowledgeRepository
from app.repositories.paper_repo import PaperRepository
from app.schemas.innovation import (
    InnovationArtifactCreate,
    InnovationArtifactRead,
    InnovationGenerateRequest,
)
from app.schemas.knowledge import KnowledgeArtifactRead
from app.schemas.paper import PaperRead
from app.services.archive_service import ArchiveService
from app.tools.mine_innovation import build_fallback_innovations


class InnovationService:
    def __init__(self) -> None:
        self.paper_repo = PaperRepository()
        self.knowledge_repo = KnowledgeRepository()
        self.innovation_repo = InnovationRepository()
        self.archive_service = ArchiveService()

    def generate(self, payload: InnovationGenerateRequest) -> InnovationArtifactRead:
        papers = self._select_papers(payload.topic)
        if len(papers) < 2:
            raise HTTPException(
                status_code=400,
                detail="至少需要 2 篇已接收论文才能生成创新点分析。请先搜索、接收并尽量 ingest 更多论文。",
            )

        knowledge = self._latest_knowledge_or_none()
        data = self._build_with_llm(payload.topic, papers, knowledge)
        generation_method = "llm"
        if data is None:
            data = build_fallback_innovations(
                papers=papers,
                knowledge_context=self._knowledge_text(knowledge),
            )
            generation_method = "fallback"

        data = self._normalize_innovation_json(data, len(papers))
        innovation_markdown = self._build_innovation_markdown(payload.topic, data)
        summary_markdown = self._build_summary_markdown(data)
        archive_markdown = self._compose_archive_markdown(
            topic=payload.topic,
            source_paper_count=len(papers),
            generation_method=generation_method,
            innovation_markdown=innovation_markdown,
            summary_markdown=summary_markdown,
        )
        markdown_path, json_path = self.archive_service.write_innovation_artifact(
            topic=payload.topic,
            markdown_content=archive_markdown,
            json_content=data,
        )

        return self.innovation_repo.create(
            InnovationArtifactCreate(
                topic=payload.topic,
                source_paper_count=len(papers),
                innovation_markdown=innovation_markdown,
                innovation_json=data,
                summary_markdown=summary_markdown,
                generation_method=generation_method,
                local_markdown_path=markdown_path,
                local_json_path=json_path,
            )
        )

    def latest(self) -> InnovationArtifactRead:
        return self.innovation_repo.latest()

    def history(self) -> list[InnovationArtifactRead]:
        return self.innovation_repo.list()

    def _select_papers(self, topic: str | None) -> list[PaperRead]:
        papers = self.paper_repo.list_accepted()
        if not topic:
            return papers
        topic_lower = topic.lower()
        selected = []
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
                selected.append(paper)
        return selected

    def _latest_knowledge_or_none(self) -> KnowledgeArtifactRead | None:
        try:
            return self.knowledge_repo.latest()
        except HTTPException:
            return None

    def _build_with_llm(
        self,
        topic: str | None,
        papers: list[PaperRead],
        knowledge: KnowledgeArtifactRead | None,
    ) -> dict[str, Any] | None:
        if not settings.openai_api_key:
            return None

        prompt = self._build_llm_prompt(topic, papers, knowledge)
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
            return json.loads(self._extract_response_text(data))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _build_llm_prompt(
        self,
        topic: str | None,
        papers: list[PaperRead],
        knowledge: KnowledgeArtifactRead | None,
    ) -> str:
        paper_blocks = []
        for paper in papers:
            paper_blocks.append(
                f"""
paper_id: {paper.id}
title: {paper.title}
relevance_score: {paper.relevance_score}
worth_reading: {paper.worth_reading}
screening_summary: {paper.screening_summary}
deep_summary: {(paper.deep_summary or paper.abstract or "")[:3000]}
"""
            )

        return f"""
你是科研创新点挖掘助手。请基于已接收并归档的论文，输出中文创新点分析 JSON。

主题：{topic or "全部已接收论文"}

要求：
1. 明确区分 evidence_based_findings 和 model_inference。
2. 不允许把纯猜测写成确定事实。
3. 创新点类别尽量覆盖：problem gap、method gap、data gap、evaluation gap、engineering gap。
4. 每个创新点必须包含 title、category、why_this_gap_exists、evidence_from_papers、possible_research_direction、expected_value、risk_level、confidence_level。
5. evidence_from_papers 必须关联 paper_id、标题或 deep_summary 依据。
6. 如果证据不足，请明确写出证据不足。
7. 只返回 JSON，不要 Markdown 代码块。

最近知识树：
{self._knowledge_text(knowledge)[:5000]}

论文材料：
{chr(10).join(paper_blocks)}
"""

    def _normalize_innovation_json(
        self,
        data: dict[str, Any],
        paper_count: int,
    ) -> dict[str, Any]:
        data.setdefault("evidence_based_findings", [])
        data.setdefault("model_inference", "暂无模型推断。")
        data.setdefault("innovation_ideas", [])
        data.setdefault("warning", None)
        if paper_count < 4:
            data["warning"] = data["warning"] or "当前已接收论文少于 4 篇，创新点覆盖可能不足。"
        return data

    def _build_innovation_markdown(self, topic: str | None, data: dict[str, Any]) -> str:
        lines = [
            f"# 创新点分析：{topic or '全部已接收论文'}",
            "",
        ]
        if data.get("warning"):
            lines.extend(["## 覆盖提醒", f"- {data['warning']}", ""])

        lines.extend(["## 论文证据：来自论文内容的直接归纳"])
        for finding in data.get("evidence_based_findings", []):
            lines.append(
                f"- P{finding.get('paper_id')}《{finding.get('title')}》：{finding.get('finding')}"
            )

        lines.extend(["", "## 模型推断：跨论文综合后的研究线索", str(data.get("model_inference", "")), ""])
        lines.append("## 候选创新点")
        for index, idea in enumerate(data.get("innovation_ideas", []), start=1):
            lines.extend(
                [
                    f"### {index}. {idea.get('title')}",
                    f"- 类别：{idea.get('category')}",
                    f"- 缺口原因：{idea.get('why_this_gap_exists')}",
                    f"- 可能研究方向：{idea.get('possible_research_direction')}",
                    f"- 预期价值：{idea.get('expected_value')}",
                    f"- 风险等级：{idea.get('risk_level')}",
                    f"- 置信度：{idea.get('confidence_level')}",
                    "- 论文证据：",
                ]
            )
            for evidence in idea.get("evidence_from_papers", []):
                lines.append(
                    f"  - P{evidence.get('paper_id')}《{evidence.get('title')}》：{evidence.get('evidence')}"
                )
            lines.append("")
        lines.append("## TODO")
        lines.append("- 后续可加入引用关系、人工评分、领域标签和实验可行性评估。")
        return "\n".join(lines)

    def _build_summary_markdown(self, data: dict[str, Any]) -> str:
        ideas = data.get("innovation_ideas", [])
        strong = [idea for idea in ideas if idea.get("confidence_level") in {"高", "中"}]
        risky = [idea for idea in ideas if idea.get("risk_level") in {"高", "中"}]
        lines = [
            "# 创新点简短总结",
            "",
            "## 当前最值得关注的 3 个方向",
        ]
        for idea in ideas[:3]:
            lines.append(f"- {idea.get('title')}（{idea.get('category')}）")
        lines.extend(["", "## 证据更强的方向"])
        for idea in (strong or ideas[:2]):
            lines.append(f"- {idea.get('title')}：置信度 {idea.get('confidence_level')}")
        lines.extend(["", "## 更冒险的方向"])
        for idea in (risky or ideas[-2:]):
            lines.append(f"- {idea.get('title')}：风险 {idea.get('risk_level')}")
        if data.get("warning"):
            lines.extend(["", "## 覆盖提醒", f"- {data['warning']}"])
        return "\n".join(lines)

    def _compose_archive_markdown(
        self,
        *,
        topic: str | None,
        source_paper_count: int,
        generation_method: str,
        innovation_markdown: str,
        summary_markdown: str,
    ) -> str:
        return f"""# 创新点归档：{topic or '全部已接收论文'}

- 来源论文数：{source_paper_count}
- 生成方式：{generation_method}

{summary_markdown}

---

{innovation_markdown}
"""

    def _knowledge_text(self, knowledge: KnowledgeArtifactRead | None) -> str:
        if knowledge is None:
            return ""
        return "\n\n".join(
            [
                knowledge.knowledge_tree_markdown,
                knowledge.learning_roadmap_markdown,
            ]
        )

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        if data.get("output_text"):
            return str(data["output_text"]).strip()
        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    parts.append(str(content.get("text", "")))
        return "".join(parts).strip()

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())
