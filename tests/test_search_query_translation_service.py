import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.agent.orchestrator import AgentOrchestrator
from app.schemas.paper import PaperRead, PaperSearchHistoryCreate, PaperSearchRequest
from app.services.feishu_service import FeishuService
from app.services.paper_service import PaperService
from app.services.search_query_translation_service import (
    SearchQueryTranslation,
    SearchQueryTranslationService,
)
from app.tools.search_papers import PaperSearchResult, _build_arxiv_query, search_papers


class FakeClient:
    def __init__(self, reply: str | None = None, error: Exception | None = None) -> None:
        self.reply = reply or '{"search_query": "VLF propagation delay ionospheric correction"}'
        self.error = error
        self.calls: list[dict[str, object]] = []

    def is_configured(self) -> bool:
        return True

    def responses_text(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error:
            raise self.error
        return self.reply


class FakePaperRepo:
    def __init__(self) -> None:
        self.created = []
        self.histories: list[PaperSearchHistoryCreate] = []
        self.existing_by_url = {}

    def create(self, payload):
        self.created.append(payload)
        return PaperRead(
            id=len(self.created),
            topic_id=payload.topic_id,
            title=payload.title,
            authors=payload.authors,
            abstract=payload.abstract,
            url=payload.url,
            source=payload.source,
            published_at=payload.published_at,
            summary=payload.summary,
            screening_summary=payload.screening_summary,
            relevance_score=payload.relevance_score,
            worth_reading=payload.worth_reading,
            status=payload.status,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )

    def create_search_history(self, payload):
        self.histories.append(payload)
        return SimpleNamespace(id=1, **payload.model_dump(), created_at="2026-01-01T00:00:00")

    def get_by_url(self, url: str):
        return self.existing_by_url.get(url)


def test_english_query_does_not_call_llm() -> None:
    client = FakeClient()
    service = SearchQueryTranslationService(client=client)

    result = service.translate_for_search("VLF propagation delay ionospheric correction")

    assert result.search_query == "VLF propagation delay ionospheric correction"
    assert result.was_translated is False
    assert result.translation_method == "not_needed"
    assert client.calls == []
    assert result.required_terms == ("VLF",)
    assert "propagation delay" in result.phrases


@pytest.mark.parametrize(
    ("source", "translated"),
    [
        ("甚低频传播时延修正", "VLF propagation delay correction"),
        ("RAG 检索增强生成在医学问答中的幻觉评估", "RAG retrieval augmented generation hallucination evaluation medical question answering"),
        ("PNT 场景下 GPS 拒止环境的鲁棒定位", "PNT GPS denied environment robust positioning"),
    ],
)
def test_chinese_query_translates_to_english_keywords(source: str, translated: str) -> None:
    client = FakeClient(reply=json.dumps({"search_query": translated}))
    service = SearchQueryTranslationService(client=client)

    result = service.translate_for_search(source)

    assert result.original_query == source
    assert result.search_query == translated
    assert result.was_translated is True
    assert result.translation_method == "llm"
    assert len(client.calls) == 1


def test_chinese_translation_parses_structured_search_terms() -> None:
    client = FakeClient(
        reply=json.dumps(
            {
                "search_query": "VLF propagation delay ionospheric correction",
                "required_terms": ["VLF"],
                "optional_terms": ["propagation", "delay", "ionosphere", "correction"],
                "phrases": ["propagation delay", "phase delay"],
                "synonyms": ["group delay", "propagation time", "phase perturbation"],
            }
        )
    )
    service = SearchQueryTranslationService(client=client)

    result = service.translate_for_search("甚低频传播时延修正")

    assert result.required_terms == ("VLF",)
    assert "correction" in result.optional_terms
    assert "propagation delay" in result.phrases
    assert "group delay" in result.synonyms


def test_chinese_translation_strips_quotes_newlines_and_period() -> None:
    client = FakeClient(reply=json.dumps({"search_query": "\"VLF\npropagation delay.\""}))
    service = SearchQueryTranslationService(client=client)

    result = service.translate_for_search("VLF 传播时延")

    assert result.search_query == "VLF propagation delay"


@pytest.mark.parametrize(
    "reply",
    [
        "not-json",
        json.dumps({"search_query": ""}),
        json.dumps({"search_query": "只剩中文"}),
        json.dumps({"search_query": "x" * 301}),
    ],
)
def test_invalid_chinese_translation_without_known_terms_is_explainable(reply: str) -> None:
    service = SearchQueryTranslationService(client=FakeClient(reply=reply))

    result = service.translate_for_search("中文检索主题")

    assert result.search_query == ""
    assert result.was_translated is False
    assert result.translation_method == "rule_fallback_unavailable"


def test_translation_failure_uses_deterministic_term_fallback() -> None:
    from app.core.llm_client import LLMClientError

    service = SearchQueryTranslationService(client=FakeClient(error=LLMClientError("timeout")))

    result = service.translate_for_search("电离层 VLF 时延")

    assert result.search_query == "ionosphere VLF delay"
    assert result.was_translated is True
    assert result.translation_method == "rule_fallback"


def test_rule_fallback_maps_known_chinese_research_terms() -> None:
    from app.core.llm_client import LLMClientError

    service = SearchQueryTranslationService(client=FakeClient(error=LLMClientError("timeout")))

    result = service.translate_for_search("甚低频传播时延修正")

    assert result.search_query == "VLF propagation delay correction"
    assert result.translation_method == "rule_fallback"


def test_unknown_chinese_query_never_builds_or_sends_empty_arxiv_query(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "app.tools.search_papers._search_arxiv_query",
        lambda query, limit: calls.append(query) or [],
    )

    with pytest.raises(ValueError, match="无法形成有效英文检索词"):
        _build_arxiv_query("中文检索主题")
    result = search_papers("中文检索主题")

    assert calls == []
    assert result.papers == []
    assert result.source == "unavailable"
    assert "英文检索词" in (result.error or "")


def test_mixed_query_rule_fallback_preserves_ascii_and_maps_chinese() -> None:
    from app.core.llm_client import LLMClientError

    service = SearchQueryTranslationService(client=FakeClient(error=LLMClientError("timeout")))

    result = service.translate_for_search("RAG 大模型幻觉")

    assert result.search_query == "RAG LLM hallucination"


def test_search_history_records_rule_fallback_method(monkeypatch) -> None:
    from app.core.llm_client import LLMClientError

    captured: dict[str, object] = {}

    def fake_search_papers(query: str, limit: int, **kwargs):
        captured["query"] = query
        return PaperSearchResult(papers=[], source="arxiv")

    monkeypatch.setattr("app.services.paper_service.search_papers", fake_search_papers)
    service = PaperService()
    service.paper_repo = FakePaperRepo()
    service.query_translation_service = SearchQueryTranslationService(
        client=FakeClient(error=LLMClientError("timeout"))
    )

    papers = service.search_and_store(
        PaperSearchRequest(topic="甚低频传播时延修正", max_results=5)
    )

    assert papers == []
    assert captured["query"] == "VLF propagation delay correction"
    assert "translation_method=rule_fallback" in service.paper_repo.histories[0].query_text


def test_chinese_translation_is_cached() -> None:
    client = FakeClient(reply=json.dumps({"search_query": "VLF propagation delay"}))
    service = SearchQueryTranslationService(client=client)

    first = service.translate_for_search("甚低频传播时延")
    second = service.translate_for_search("甚低频传播时延")

    assert first == second
    assert len(client.calls) == 1


def test_paper_service_uses_effective_english_query_and_preserves_original_history(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_search_papers(query: str, limit: int, **kwargs):
        captured["query"] = query
        captured["limit"] = limit
        captured["required_terms"] = kwargs["required_terms"]
        return PaperSearchResult(
            papers=[
                {
                    "title": "VLF propagation delay correction for ionospheric channels",
                    "authors": "A. Researcher",
                    "abstract": "We study VLF propagation delay and ionospheric correction.",
                    "url": "https://arxiv.org/abs/2601.00001",
                    "source": "arxiv",
                    "published_at": "2026-01-01",
                }
            ],
            source="arxiv",
            query_level=2,
            effective_arxiv_query='all:VLF AND (all:delay OR all:correction)',
            attempted_queries=[
                {"query_level": 1, "effective_arxiv_query": "strict", "success": True},
                {"query_level": 2, "effective_arxiv_query": "loose", "success": True},
            ],
        )

    monkeypatch.setattr("app.services.paper_service.search_papers", fake_search_papers)
    monkeypatch.setattr("app.services.paper_service.settings", SimpleNamespace(openai_api_key=None))
    service = PaperService()
    service.paper_repo = FakePaperRepo()
    service.query_translation_service = SimpleNamespace(
        translate_for_search=lambda query: SearchQueryTranslation(
            original_query=query,
            search_query="VLF propagation delay ionospheric correction",
            was_translated=True,
            translation_method="llm",
            required_terms=("VLF",),
            optional_terms=("propagation", "delay", "ionosphere", "correction"),
            phrases=("propagation delay",),
            synonyms=("group delay",),
        )
    )

    papers = service.search_and_store(PaperSearchRequest(topic="甚低频传播时延修正", max_results=1))

    assert captured == {
        "query": "VLF propagation delay ionospheric correction",
        "limit": 1,
        "required_terms": ("VLF",),
    }
    assert len(papers) == 1
    history = service.paper_repo.histories[0]
    assert history.topic == "甚低频传播时延修正"
    assert "original_query=甚低频传播时延修正" in history.query_text
    assert "effective_search_query=VLF propagation delay ionospheric correction" in history.query_text
    assert "was_translated=true" in history.query_text
    assert "translation_method=llm" in history.query_text
    assert "query_level=2" in history.query_text
    assert "final_arxiv_query=all:VLF AND (all:delay OR all:correction)" in history.query_text
    assert "attempted_query_count=2" in history.query_text


def test_rule_based_screening_uses_effective_english_query() -> None:
    service = PaperService()
    result = service._rule_based_screening(
        original_topic="甚低频传播时延修正",
        effective_search_query="VLF propagation delay ionospheric correction",
        paper={
            "title": "VLF propagation delay correction",
            "abstract": "This paper models ionospheric correction for propagation delay.",
        },
    )

    assert result["relevance_score"] >= 4
    assert result["worth_reading"] == "值得继续看"
    assert "甚低频传播时延修正" in result["screening_summary"]


def test_feishu_chinese_message_reaches_search_papers_with_english_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(AgentOrchestrator, "_route_with_llm", lambda self, message: None)
    monkeypatch.setattr("app.services.paper_service.settings", SimpleNamespace(openai_api_key=None))
    monkeypatch.setattr(
        "app.services.paper_service.SearchQueryTranslationService.translate_for_search",
        lambda self, query: SearchQueryTranslation(
            original_query=query,
            search_query="VLF propagation delay ionospheric correction",
            was_translated=True,
            translation_method="llm",
            required_terms=("VLF",),
        ),
    )

    def fake_search_papers(query: str, limit: int, **kwargs):
        captured["query"] = query
        captured["limit"] = limit
        return PaperSearchResult(
            papers=[
                {
                    "title": "VLF propagation delay correction",
                    "authors": "A. Researcher",
                    "abstract": "VLF propagation delay and ionospheric correction.",
                    "url": "https://arxiv.org/abs/2601.00002",
                    "source": "arxiv",
                    "published_at": "2026-01-02",
                }
            ],
            source="arxiv",
            query_level=1,
            effective_arxiv_query="all:VLF",
        )

    monkeypatch.setattr("app.services.paper_service.search_papers", fake_search_papers)
    service = FeishuService()
    replies: list[str] = []
    monkeypatch.setattr(
        service,
        "_reply_to_feishu",
        lambda message_id, text, **kwargs: replies.append(text) or {"success": True},
    )
    payload = {
        "schema": "2.0",
        "header": {"event_id": "evt_search_cn", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_1"}},
            "message": {
                "message_id": "msg_search_cn",
                "chat_id": "oc_1",
                "message_type": "text",
                "content": json.dumps({"text": "帮我搜索 1 篇甚低频传播时延修正论文"}, ensure_ascii=False),
            },
        },
    }

    background = BackgroundTasks()
    result = service.handle_webhook(
        raw_body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={},
        background_tasks=background,
    )
    task = background.tasks[0]
    task.func(*task.args, **task.kwargs)

    assert result["message"] == "飞书事件已接收，后台处理中"
    assert captured["query"] == "VLF propagation delay ionospheric correction"
    assert replies
    assert "已调用工具" not in replies[0]
    assert "路由方式" not in replies[0]
    assert "effective_search_query" not in replies[0]
    assert "query_level" not in replies[0]


def test_date_range_parsing_supports_chinese_recent_and_since_year() -> None:
    service = PaperService()

    assert service._extract_published_range("帮我搜索几篇 VLF 传播时延相关的论文，要近十年的") == (
        date(date.today().year - 10, date.today().month, date.today().day),
        date.today(),
    )
    assert service._extract_published_range("近五年 VLF 论文") == (
        date(date.today().year - 5, date.today().month, date.today().day),
        date.today(),
    )
    assert service._extract_published_range("2018 年以来 VLF 论文") == (date(2018, 1, 1), date.today())
    assert service._extract_published_range("2020 到 2025 年 VLF 论文") == (
        date(2020, 1, 1),
        date(2025, 12, 31),
    )


def test_time_and_count_constraints_are_not_sent_to_translation(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_search_papers(query: str, limit: int, **kwargs):
        return PaperSearchResult(papers=[], source="arxiv", query_level=1, effective_arxiv_query="all:VLF")

    def fake_translate(query: str):
        seen["query"] = query
        return SearchQueryTranslation(
            original_query=query,
            search_query="VLF propagation delay",
            was_translated=True,
            translation_method="llm",
        )

    monkeypatch.setattr("app.services.paper_service.search_papers", fake_search_papers)
    service = PaperService()
    service.paper_repo = FakePaperRepo()
    service.query_translation_service = SimpleNamespace(translate_for_search=fake_translate)

    service.search_and_store(PaperSearchRequest(topic="帮我搜索几篇 VLF 传播时延相关的论文，要近十年的", max_results=3))

    assert seen["query"] == "VLF 传播时延"


def test_existing_same_url_is_reused_without_duplicate_create(monkeypatch) -> None:
    existing = PaperRead(
        id=99,
        title="Existing Paper",
        abstract="Existing abstract",
        url="https://arxiv.org/abs/2401.00099",
        source="arxiv",
        status="found",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )

    def fake_search_papers(query: str, limit: int, **kwargs):
        return PaperSearchResult(
            papers=[
                {
                    "title": "New title should not be inserted",
                    "authors": "A. Researcher",
                    "abstract": "VLF propagation delay.",
                    "url": "https://arxiv.org/abs/2401.00099",
                    "source": "arxiv",
                    "published_at": "2024-01-01",
                }
            ],
            source="arxiv",
            query_level=1,
            effective_arxiv_query="all:VLF",
        )

    monkeypatch.setattr("app.services.paper_service.search_papers", fake_search_papers)
    service = PaperService()
    service.paper_repo = FakePaperRepo()
    service.paper_repo.existing_by_url[existing.url] = existing
    service.query_translation_service = SimpleNamespace(
        translate_for_search=lambda query: SearchQueryTranslation(
            original_query=query,
            search_query="VLF propagation delay",
            was_translated=False,
            translation_method="not_needed",
            required_terms=("VLF",),
        )
    )

    papers = service.search_and_store(PaperSearchRequest(topic="VLF propagation delay", max_results=1))

    assert papers == [existing]
    assert service.paper_repo.created == []
