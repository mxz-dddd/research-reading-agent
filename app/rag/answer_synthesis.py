"""PaperWeave LLM 引用式回答合成。

只基于检索到的 evidence chunks 生成回答，并强制 [chunk:<chunk_id>] 引用标记。
引用校验失败或 LLM 不可用时，由调用方降级到模板回答。
"""

import logging
import re
from typing import Any

from app.core.config import settings
from app.core.llm_client import LLMClientError, OpenAICompatibleClient
from app.schemas.rag import RagSearchChunk

logger = logging.getLogger(__name__)

CITATION_PATTERN = re.compile(r"\[chunk:([^\]\s]+)\]")

SYNTHESIS_SYSTEM_PROMPT = """你是一个科研论文阅读助手。请只根据用户提供的 evidence 片段回答问题，遵守以下规则：
1. 只使用 evidence 中出现的信息，不要编造 evidence 之外的内容。
2. 每个关键论断后面必须紧跟引用标记，格式严格为 [chunk:<chunk_id>]，chunk_id 必须来自 evidence 列表。
3. 如果 evidence 不足以回答问题，明确说明"现有证据不足"，并指出缺少什么信息。
4. 用中文回答，保持简洁、结构清晰。
5. 不要输出 evidence 原文之外的引用编号或参考文献格式。"""

_MAX_CHUNK_CHARS = 1200


def extract_citations(text: str) -> list[str]:
    return CITATION_PATTERN.findall(text)


def validate_citations(
    answer: str,
    evidence_chunks: list[RagSearchChunk],
) -> dict[str, Any]:
    evidence_ids = {chunk.chunk_id for chunk in evidence_chunks}
    cited = extract_citations(answer)
    cited_unique = list(dict.fromkeys(cited))
    invalid = [chunk_id for chunk_id in cited_unique if chunk_id not in evidence_ids]
    valid_cited = [chunk_id for chunk_id in cited_unique if chunk_id in evidence_ids]
    return {
        "cited_chunk_ids": cited_unique,
        "valid_cited_chunk_ids": valid_cited,
        "invalid_citations": invalid,
        "citation_count": len(cited),
        "evidence_count": len(evidence_chunks),
        "valid": bool(valid_cited) and not invalid,
    }


class LLMAnswerSynthesizer:
    def __init__(self, client: OpenAICompatibleClient | None = None) -> None:
        self.client = client or OpenAICompatibleClient()

    def should_use_llm(self) -> bool:
        mode = (settings.rag_answer_mode or "auto").strip().lower()
        if mode == "template":
            return False
        if mode in {"auto", "llm"}:
            return self.client.is_configured()
        return False

    def synthesize(
        self,
        *,
        query: str,
        evidence_chunks: list[RagSearchChunk],
    ) -> dict[str, Any] | None:
        """返回 {"answer", "citations", "valid", "model"}；LLM 调用失败返回 None。"""
        if not evidence_chunks:
            return None
        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(query, evidence_chunks)},
        ]
        try:
            answer = self.client.chat_text(messages)
        except LLMClientError as exc:
            # 不再完全静默：记录可见日志，由调用方降级到模板回答。
            logger.warning(
                "LLM answer synthesis failed, falling back to template answer (model=%s): %s",
                self.client.model,
                exc,
            )
            return None
        citations = validate_citations(answer, evidence_chunks)
        return {
            "answer": answer.strip(),
            "citations": citations,
            "valid": citations["valid"],
            "model": self.client.model,
        }

    def _build_user_prompt(self, query: str, evidence_chunks: list[RagSearchChunk]) -> str:
        lines = [f"问题：{query}", "", "Evidence 片段："]
        for chunk in evidence_chunks:
            header_parts = [f"chunk_id={chunk.chunk_id}", f"paper_id={chunk.paper_id}"]
            if chunk.section_title:
                header_parts.append(f"section={chunk.section_title}")
            if chunk.contextual_header:
                header_parts.append(f"context={chunk.contextual_header}")
            content = chunk.content
            if len(content) > _MAX_CHUNK_CHARS:
                content = content[:_MAX_CHUNK_CHARS] + "..."
            lines.append(f"[chunk:{chunk.chunk_id}] ({'; '.join(header_parts)})")
            lines.append(content)
            lines.append("")
        lines.append("请根据以上 evidence 回答问题，并按规则添加 [chunk:<chunk_id>] 引用。")
        return "\n".join(lines)
