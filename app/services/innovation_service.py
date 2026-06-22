import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from fastapi import HTTPException

from app.core.config import settings
from app.core.llm_client import LLMClientError, OpenAICompatibleClient
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
        client = OpenAICompatibleClient()
        if not client.is_configured():
            return None

        prompt = self._build_llm_prompt(topic, papers, knowledge)
        try:
            text = client.responses_text(
                prompt,
                instructions=(
                    "You are a research innovation mining assistant. Return exactly one "
                    "valid JSON object and do not include Markdown fences."
                ),
            )
            return json.loads(text)
        except (LLMClientError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"innovation LLM fallback: {type(exc).__name__}: {exc}")
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
deep_summary:
{(paper.deep_summary or paper.abstract or "")[:7000]}
"""
            )

        return f"""
You are a research innovation mining assistant.

Analyze the archived papers and return exactly one valid JSON object.
All natural-language values must be written in Simplified Chinese.
Do not use Markdown code fences.
Do not include any explanation before or after the JSON.

Topic:
{topic or "All accepted papers"}

The top-level JSON object MUST contain these exact keys:

{{
  "topic": "string",
  "evidence_based_findings": [
    {{
      "paper_id": 1,
      "title": "exact paper title",
      "finding": "evidence-based finding in Chinese"
    }}
  ],
  "model_inference": "non-empty Chinese Markdown string",
  "innovation_ideas": [
    {{
      "title": "innovation title",
      "category": "problem gap",
      "why_this_gap_exists": "why the gap exists",
      "evidence_from_papers": [
        {{
          "paper_id": 1,
          "title": "exact paper title",
          "evidence": "specific evidence from the paper summary"
        }}
      ],
      "possible_research_direction": "specific research direction",
      "expected_value": "expected scientific or engineering value",
      "risk_level": "\u9ad8",
      "confidence_level": "\u4e2d"
    }}
  ]
}}

Strict requirements:

1. innovation_ideas MUST contain 6 to 10 complete objects.
2. Never return an empty innovation_ideas list.
3. Never replace innovation_ideas with innovation_points,
   cross_category_summary, recommendations, gaps, or another key.
4. evidence_based_findings MUST contain 4 to 8 items.
5. Every evidence_based_findings item must use a real paper_id
   and the exact corresponding paper title.
6. model_inference must be a non-empty string containing
   cross-paper conclusions and their reasoning.
7. Each innovation idea must contain all fields shown above.
8. evidence_from_papers must contain at least one real paper.
9. category should collectively cover:
   problem gap, method gap, data gap,
   evaluation gap, and engineering gap.
10. risk_level must be one of:
    "\u9ad8", "\u4e2d", "\u4f4e".
11. confidence_level must be one of:
    "\u9ad8", "\u4e2d", "\u4f4e".
12. Separate direct paper evidence from model inference.
13. Do not claim unsupported facts.
14. When evidence is limited, explicitly state the limitation,
    but still provide a grounded research direction.
15. Return JSON only.

Latest knowledge tree and learning roadmap:

{self._knowledge_text(knowledge)[:8000]}

Archived paper materials:

{chr(10).join(paper_blocks)}
"""

    def _normalize_innovation_json(
        self,
        data: dict[str, Any],
        paper_count: int,
    ) -> dict[str, Any]:
        raw_ideas = (
            data.get("innovation_ideas")
            or data.get("innovation_points")
            or []
        )

        normalized_ideas = []
        if isinstance(raw_ideas, list):
            for idea in raw_ideas:
                if not isinstance(idea, dict):
                    continue

                normalized_idea = dict(idea)
                raw_evidence = idea.get("evidence_from_papers") or []
                normalized_evidence = []

                if isinstance(raw_evidence, list):
                    for evidence in raw_evidence:
                        if not isinstance(evidence, dict):
                            continue

                        normalized_item = dict(evidence)
                        normalized_item["paper_id"] = evidence.get("paper_id", "?")
                        normalized_item["title"] = (
                            evidence.get("title")
                            or "\u672a\u6307\u5b9a\u8bba\u6587"
                        )
                        normalized_item["evidence"] = str(
                            evidence.get("evidence")
                            or evidence.get("basis")
                            or evidence.get("statement")
                            or "\u8bc1\u636e\u6587\u672c\u672a\u63d0\u4f9b"
                        ).strip()

                        normalized_evidence.append(normalized_item)

                normalized_idea["evidence_from_papers"] = normalized_evidence
                normalized_ideas.append(normalized_idea)

        data["innovation_ideas"] = normalized_ideas

        raw_findings = data.get("evidence_based_findings") or []
        normalized_findings = []

        if isinstance(raw_findings, list):
            for item in raw_findings:
                if not isinstance(item, dict):
                    continue

                finding_text = str(
                    item.get("finding")
                    or item.get("statement")
                    or item.get("description")
                    or ""
                ).strip()

                paper_id = item.get("paper_id")
                title = item.get("title")
                evidence_items = item.get("evidence_from_papers") or []

                if paper_id is not None or title:
                    normalized_findings.append(
                        {
                            "paper_id": paper_id if paper_id is not None else "?",
                            "title": title or "\u672a\u6307\u5b9a\u8bba\u6587",
                            "finding": finding_text or "\u6682\u65e0\u76f4\u63a5\u5f52\u7eb3",
                        }
                    )
                    continue

                if isinstance(evidence_items, list) and evidence_items:
                    for evidence in evidence_items:
                        if not isinstance(evidence, dict):
                            continue

                        evidence_text = str(
                            evidence.get("evidence")
                            or evidence.get("basis")
                            or evidence.get("statement")
                            or ""
                        ).strip()

                        combined_text = finding_text
                        if evidence_text:
                            combined_text = (
                                f"{combined_text} "
                                f"\u8bc1\u636e\uff1a{evidence_text}"
                                if combined_text
                                else evidence_text
                            )

                        normalized_findings.append(
                            {
                                "paper_id": evidence.get("paper_id", "?"),
                                "title": (
                                    evidence.get("title")
                                    or "\u672a\u6307\u5b9a\u8bba\u6587"
                                ),
                                "finding": combined_text or "\u6682\u65e0\u76f4\u63a5\u5f52\u7eb3",
                            }
                        )
                elif finding_text:
                    normalized_findings.append(
                        {
                            "paper_id": "?",
                            "title": "\u8de8\u8bba\u6587\u5f52\u7eb3",
                            "finding": finding_text,
                        }
                    )

        data["evidence_based_findings"] = normalized_findings

        model_inference = data.get(
            "model_inference",
            "\u6682\u65e0\u6a21\u578b\u63a8\u65ad",
        )

        if isinstance(model_inference, list):
            inference_lines = []

            for item in model_inference:
                if isinstance(item, dict):
                    statement = str(
                        item.get("statement")
                        or item.get("inference")
                        or ""
                    ).strip()
                    basis = str(item.get("basis") or "").strip()

                    if statement:
                        line = f"- {statement}"
                        if basis:
                            line += f"\n  - \u4f9d\u636e\uff1a{basis}"
                        inference_lines.append(line)
                else:
                    inference_lines.append(f"- {item}")

            data["model_inference"] = (
                "\n".join(inference_lines)
                or "\u6682\u65e0\u6a21\u578b\u63a8\u65ad"
            )

        elif isinstance(model_inference, dict):
            data["model_inference"] = json.dumps(
                model_inference,
                ensure_ascii=False,
                indent=2,
            )
        else:
            data["model_inference"] = str(model_inference)

        data.setdefault("warning", None)

        if paper_count < 4:
            data["warning"] = (
                "\u5f53\u524d\u5df2\u63a5\u6536\u8bba\u6587\u5c11\u4e8e "
                "4 "
                "\u7bc7\uff0c\u521b\u65b0\u70b9\u8986\u76d6\u53ef\u80fd\u4e0d\u8db3\u3002"
            )

        return data

    def _build_innovation_markdown(
        self,
        topic: str | None,
        data: dict[str, Any],
    ) -> str:
        display_topic = topic or "\u5168\u90e8\u5df2\u63a5\u6536\u8bba\u6587"
        lines = [
            f"# \u521b\u65b0\u70b9\u5206\u6790\uff1a{display_topic}",
            "",
        ]

        if data.get("warning"):
            lines.extend(
                [
                    "## \u8986\u76d6\u63d0\u9192",
                    f"- {data['warning']}",
                    "",
                ]
            )

        lines.append("## \u8bba\u6587\u8bc1\u636e\uff1a\u6765\u81ea\u8bba\u6587\u5185\u5bb9\u7684\u76f4\u63a5\u5f52\u7eb3")

        for finding in data.get("evidence_based_findings", []):
            paper_id = finding.get("paper_id")
            title = finding.get("title") or "\u8de8\u8bba\u6587\u5f52\u7eb3"
            finding_text = finding.get("finding") or "\u6682\u65e0\u76f4\u63a5\u5f52\u7eb3"

            if paper_id in {None, "", "?"}:
                lines.append(f"- \u300a{title}\u300b\uff1a{finding_text}")
            else:
                lines.append(
                    f"- P{paper_id}\u300a{title}\u300b\uff1a{finding_text}"
                )

        lines.extend(
            [
                "",
                "## \u6a21\u578b\u63a8\u65ad\uff1a\u8de8\u8bba\u6587\u7efc\u5408\u540e\u7684\u7814\u7a76\u7ebf\u7d22",
                str(data.get("model_inference", "")),
                "",
                "## \u5019\u9009\u521b\u65b0\u70b9",
            ]
        )

        for index, idea in enumerate(
            data.get("innovation_ideas", []),
            start=1,
        ):
            lines.extend(
                [
                    f"### {index}. {idea.get('title')}",
                    f"- \u7c7b\u522b\uff1a{idea.get('category')}",
                    f"- \u7f3a\u53e3\u539f\u56e0\uff1a{idea.get('why_this_gap_exists')}",
                    f"- \u53ef\u80fd\u7814\u7a76\u65b9\u5411\uff1a{idea.get('possible_research_direction')}",
                    f"- \u9884\u671f\u4ef7\u503c\uff1a{idea.get('expected_value')}",
                    f"- \u98ce\u9669\u7b49\u7ea7\uff1a{idea.get('risk_level')}",
                    f"- \u7f6e\u4fe1\u5ea6\uff1a{idea.get('confidence_level')}",
                    "- \u8bba\u6587\u8bc1\u636e\uff1a",
                ]
            )

            for evidence in idea.get("evidence_from_papers", []):
                evidence_title = evidence.get("title") or "\u672a\u6307\u5b9a\u8bba\u6587"
                evidence_text = (
                    evidence.get("evidence")
                    or evidence.get("basis")
                    or evidence.get("statement")
                    or "\u8bc1\u636e\u6587\u672c\u672a\u63d0\u4f9b"
                )

                lines.append(
                    f"  - P{evidence.get('paper_id', '?')}"
                    f"\u300a{evidence_title}\u300b"
                    f"\uff1a{evidence_text}"
                )

            lines.append("")

        lines.append("## TODO")
        lines.append(
            "- \u540e\u7eed\u53ef\u52a0\u5165\u5f15\u7528\u5173\u7cfb\u3001"
            "\u4eba\u5de5\u8bc4\u5206\u3001\u9886\u57df\u6807\u7b7e\u548c"
            "\u5b9e\u9a8c\u53ef\u884c\u6027\u8bc4\u4f30\u3002"
        )

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
