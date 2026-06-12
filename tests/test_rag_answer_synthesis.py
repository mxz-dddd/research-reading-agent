import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.llm_client import LLMClientError, OpenAICompatibleClient
from app.rag.answer_synthesis import (
    LLMAnswerSynthesizer,
    extract_citations,
    validate_citations,
)
from app.schemas.rag import RagSearchChunk


def _chunk(chunk_id: str, content: str = "evidence content") -> RagSearchChunk:
    return RagSearchChunk(
        score=1.0,
        chunk_id=chunk_id,
        paper_id="1",
        chunk_index=0,
        content=content,
        content_preview=content[:50],
    )


class FakeClient(OpenAICompatibleClient):
    def __init__(self, *, reply: str | None = None, error: bool = False) -> None:
        super().__init__(api_key="fake-key", model="fake-model", base_url="https://example.invalid/v1")
        self.reply = reply
        self.error = error
        self.last_messages: list[dict] | None = None

    def chat_text(self, messages, *, temperature: float = 0.2) -> str:
        self.last_messages = messages
        if self.error or self.reply is None:
            raise LLMClientError("simulated failure")
        return self.reply


def test_extract_citations() -> None:
    text = "结论 A [chunk:paper-1-0-abc]。结论 B [chunk:paper-1-1-def]，再次引用 [chunk:paper-1-0-abc]。"
    assert extract_citations(text) == ["paper-1-0-abc", "paper-1-1-def", "paper-1-0-abc"]


def test_validate_citations_valid() -> None:
    chunks = [_chunk("c1"), _chunk("c2")]
    result = validate_citations("观点 [chunk:c1]，另一观点 [chunk:c2]。", chunks)
    assert result["valid"] is True
    assert result["cited_chunk_ids"] == ["c1", "c2"]
    assert result["invalid_citations"] == []


def test_validate_citations_invalid_id() -> None:
    chunks = [_chunk("c1")]
    result = validate_citations("观点 [chunk:c1]，幻觉引用 [chunk:ghost]。", chunks)
    assert result["valid"] is False
    assert result["invalid_citations"] == ["ghost"]


def test_validate_citations_requires_at_least_one() -> None:
    chunks = [_chunk("c1")]
    result = validate_citations("没有任何引用的回答。", chunks)
    assert result["valid"] is False
    assert result["citation_count"] == 0


def test_synthesize_success_includes_evidence_in_prompt() -> None:
    client = FakeClient(reply="方法是 X [chunk:c1]。")
    synthesizer = LLMAnswerSynthesizer(client=client)

    result = synthesizer.synthesize(query="这篇论文的方法是什么？", evidence_chunks=[_chunk("c1", "method X")])

    assert result is not None
    assert result["valid"] is True
    assert result["model"] == "fake-model"
    user_prompt = client.last_messages[1]["content"]
    assert "[chunk:c1]" in user_prompt
    assert "method X" in user_prompt


def test_synthesize_returns_none_on_llm_error() -> None:
    synthesizer = LLMAnswerSynthesizer(client=FakeClient(error=True))
    assert synthesizer.synthesize(query="q", evidence_chunks=[_chunk("c1")]) is None


def test_synthesize_flags_invalid_citations() -> None:
    synthesizer = LLMAnswerSynthesizer(client=FakeClient(reply="编造 [chunk:ghost]。"))
    result = synthesizer.synthesize(query="q", evidence_chunks=[_chunk("c1")])
    assert result is not None
    assert result["valid"] is False


def test_synthesize_skips_empty_evidence() -> None:
    synthesizer = LLMAnswerSynthesizer(client=FakeClient(reply="anything"))
    assert synthesizer.synthesize(query="q", evidence_chunks=[]) is None


def test_should_use_llm_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    synthesizer = LLMAnswerSynthesizer(client=FakeClient(reply="x"))

    monkeypatch.setattr(
        "app.rag.answer_synthesis.settings", SimpleNamespace(rag_answer_mode="template")
    )
    assert synthesizer.should_use_llm() is False

    monkeypatch.setattr(
        "app.rag.answer_synthesis.settings", SimpleNamespace(rag_answer_mode="auto")
    )
    assert synthesizer.should_use_llm() is True

    unconfigured = LLMAnswerSynthesizer(
        client=OpenAICompatibleClient(api_key=None, model="m", base_url="https://example.invalid/v1")
    )
    assert unconfigured.should_use_llm() is False
