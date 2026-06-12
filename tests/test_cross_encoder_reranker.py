from types import SimpleNamespace

import pytest

from app.rag.rerankers import CrossEncoderReranker, DeterministicReranker, get_reranker
from app.schemas.rag import RagSearchChunk


def _chunk(chunk_id: str, content: str, score: float = 0.5) -> RagSearchChunk:
    return RagSearchChunk(
        score=score,
        chunk_id=chunk_id,
        paper_id="1",
        chunk_index=0,
        content=content,
        content_preview=content,
        retrieval_scores={"rrf": score},
    )


def test_default_reranker_remains_deterministic() -> None:
    reranker, provider = get_reranker(None)

    assert isinstance(reranker, DeterministicReranker)
    assert provider == "deterministic"


def test_cross_encoder_missing_dependency_has_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_import_error(name: str):
        raise ImportError(name)

    monkeypatch.setattr("app.rag.rerankers.importlib.import_module", raise_import_error)

    with pytest.raises(RuntimeError, match="requirements-paperweave-reranker.txt"):
        get_reranker("cross-encoder", model_name="fake-model")


def test_cross_encoder_orders_by_fake_model_score(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCrossEncoder:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def predict(self, pairs):
            return [0.9 if "exact answer" in document else 0.2 for _query, document in pairs]

    monkeypatch.setattr(
        "app.rag.rerankers.importlib.import_module",
        lambda name: SimpleNamespace(CrossEncoder=FakeCrossEncoder),
    )
    reranker = CrossEncoderReranker(model_name="fake-cross-encoder")
    chunks = [_chunk("low", "less relevant"), _chunk("high", "exact answer text")]

    result = reranker.rerank("query", chunks)

    assert [chunk.chunk_id for chunk in result] == ["high", "low"]
    assert result[0].rerank_score == pytest.approx(0.9)
    assert "cross-encoder(fake-cross-encoder)" in result[0].score_reason


def test_unknown_reranker_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported reranker provider"):
        get_reranker("unknown")
