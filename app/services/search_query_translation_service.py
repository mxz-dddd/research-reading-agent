from __future__ import annotations

import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.core.llm_client import LLMClientError, OpenAICompatibleClient

logger = logging.getLogger(__name__)

CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
MAX_CACHE_SIZE = 256
RULE_FALLBACK_TERMS = (
    ("检索增强生成", "retrieval augmented generation"),
    ("时间延迟", "time delay"),
    ("低电离层", "lower ionosphere"),
    ("太阳耀斑", "solar flare"),
    ("甚低频", "VLF"),
    ("超低频", "ULF"),
    ("传播", "propagation"),
    ("时延", "delay"),
    ("修正", "correction"),
    ("校正", "calibration"),
    ("电离层", "ionosphere"),
    ("D区", "D-region"),
    ("遥感", "remote sensing"),
    ("导航", "navigation"),
    ("授时", "timing"),
    ("定位", "positioning"),
    ("大模型", "LLM"),
    ("幻觉", "hallucination"),
)


@dataclass(frozen=True)
class SearchQueryTranslation:
    original_query: str
    search_query: str
    was_translated: bool
    translation_method: str
    required_terms: tuple[str, ...] = ()
    optional_terms: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()


class SearchQueryTranslationService:
    def __init__(self, client: OpenAICompatibleClient | Any | None = None) -> None:
        self.client = client
        self._cache: OrderedDict[str, SearchQueryTranslation] = OrderedDict()

    def translate_for_search(self, query: str) -> SearchQueryTranslation:
        original_query = str(query or "").strip()
        if not original_query:
            return SearchQueryTranslation(
                original_query=original_query,
                search_query=original_query,
                was_translated=False,
                translation_method="not_needed",
                **self._local_search_terms(original_query),
            )

        contains_chinese = self._contains_chinese(original_query)
        if not contains_chinese:
            logger.info(
                "search_query_translation chinese_detected=False query_len=%s preview=%s method=not_needed",
                len(original_query),
                self._safe_preview(original_query),
            )
            return SearchQueryTranslation(
                original_query=original_query,
                search_query=original_query,
                was_translated=False,
                translation_method="not_needed",
                **self._local_search_terms(original_query),
            )

        cached = self._cache.get(original_query)
        if cached is not None:
            self._cache.move_to_end(original_query)
            logger.info(
                "search_query_translation chinese_detected=True cache_hit=True query_len=%s preview=%s method=%s",
                len(original_query),
                self._safe_preview(original_query),
                cached.translation_method,
            )
            return cached

        start = time.monotonic()
        try:
            client = self.client or OpenAICompatibleClient()
            if hasattr(client, "is_configured") and not client.is_configured():
                raise LLMClientError("OpenAI-compatible client is not configured")

            text = client.responses_text(
                self._build_prompt(original_query),
                instructions=(
                    "You translate Chinese research topics into concise English academic "
                    "search keywords for arXiv. Return strict JSON only."
                ),
                temperature=0.0,
            )
            parsed = json.loads(text)
            search_query = self._normalize_search_query(parsed.get("search_query"))
            result = SearchQueryTranslation(
                original_query=original_query,
                search_query=search_query,
                was_translated=True,
                translation_method="llm",
                required_terms=self._normalize_terms(parsed.get("required_terms")),
                optional_terms=self._normalize_terms(parsed.get("optional_terms")),
                phrases=self._normalize_terms(parsed.get("phrases")),
                synonyms=self._normalize_terms(parsed.get("synonyms")),
            )
            self._remember(original_query, result)
            logger.info(
                "search_query_translation chinese_detected=True success=True elapsed_ms=%s query_len=%s preview=%s method=llm",
                int((time.monotonic() - start) * 1000),
                len(original_query),
                self._safe_preview(original_query),
            )
            return result
        except (LLMClientError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            fallback_query = self._rule_fallback(original_query)
            fallback_method = "rule_fallback" if fallback_query else "rule_fallback_unavailable"
            result = SearchQueryTranslation(
                original_query=original_query,
                search_query=fallback_query,
                was_translated=bool(fallback_query),
                translation_method=fallback_method,
                **self._local_search_terms(fallback_query),
            )
            self._remember(original_query, result)
            logger.warning(
                "search_query_translation chinese_detected=True success=False elapsed_ms=%s query_len=%s preview=%s method=%s error_type=%s",
                int((time.monotonic() - start) * 1000),
                len(original_query),
                self._safe_preview(original_query),
                fallback_method,
                type(exc).__name__,
            )
            return result

    def _build_prompt(self, query: str) -> str:
        return f"""
Convert this Chinese research topic or user search request into English arXiv academic search keywords.

Original query:
{query}

Rules:
- Output 3-10 English academic keywords or short noun phrases in search_query.
- Preserve abbreviations exactly when present, such as VLF, RAG, LLM, PNT, GPS, GNSS, SAR, EEG.
- Preserve proper nouns, formula names, chemical symbols, model names, frequencies, and units.
- Remove command words and constraints such as search, find papers, help me, recommend, recent, counts, and date ranges.
- Do not invent new domain concepts that are not implied by the query.
- Do not include Chinese-only text.
- required_terms should contain only truly required core entities, especially abbreviations and proper nouns.
- Do not put every word in required_terms.
- optional_terms should contain broader topical words.
- phrases should contain important exact phrases.
- synonyms should contain close academic alternatives that help arXiv recall.
- Return strict JSON only with this shape:
{{
  "search_query": "...",
  "required_terms": ["..."],
  "optional_terms": ["..."],
  "phrases": ["..."],
  "synonyms": ["..."]
}}
""".strip()

    def _normalize_search_query(self, value: Any) -> str:
        text = str(value or "").strip()
        text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        text = text.strip("'\"`“”‘’ ")
        text = text.rstrip(".。;；")
        text = " ".join(text.split())
        if not text:
            raise ValueError("translated search_query is empty")
        if len(text) > 300:
            raise ValueError("translated search_query is too long")
        if self._contains_chinese(text) and not ASCII_LETTER_RE.search(text):
            raise ValueError("translated search_query is still Chinese-only")
        return text

    def _normalize_terms(self, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        raw_terms: list[Any] | tuple[Any, ...]
        if isinstance(value, str):
            raw_terms = [value]
        elif isinstance(value, list | tuple):
            raw_terms = value
        else:
            return ()
        seen: set[str] = set()
        result: list[str] = []
        for item in raw_terms:
            term = str(item or "").strip().strip("'\"`“”‘’ ")
            term = " ".join(term.replace("\r", " ").replace("\n", " ").split())
            if not term or len(term) > 80:
                continue
            if self._contains_chinese(term) and not ASCII_LETTER_RE.search(term):
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(term)
        return tuple(result)

    def _local_search_terms(self, query: str) -> dict[str, tuple[str, ...]]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*|\d+(?:\.\d+)?", query)
        required: list[str] = []
        optional: list[str] = []
        for token in tokens:
            if token.upper() in {"VLF", "PNT", "GPS", "RAG", "LLM", "LWPC", "GNSS", "SAR", "EEG"}:
                required.append(token.upper())
            elif token.lower() not in {
                "paper",
                "papers",
                "research",
                "study",
                "related",
                "several",
                "recent",
                "search",
            }:
                optional.append(token)
        phrases = [
            phrase
            for phrase in (
                "propagation delay",
                "phase delay",
                "group delay",
                "low ionosphere",
                "solar flare",
                "Wait-Spies",
            )
            if phrase.lower() in query.lower()
        ]
        if not required and optional:
            required.append(optional.pop(0))
        return {
            "required_terms": self._normalize_terms(required),
            "optional_terms": self._normalize_terms(optional),
            "phrases": self._normalize_terms(phrases),
            "synonyms": (),
        }

    def _rule_fallback(self, query: str) -> str:
        candidates: list[tuple[int, int, str]] = []
        for source, target in RULE_FALLBACK_TERMS:
            for match in re.finditer(re.escape(source), query, flags=re.IGNORECASE):
                candidates.append((match.start(), match.end(), target))
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", query):
            candidates.append((match.start(), match.end(), match.group(0)))

        selected: list[tuple[int, int, str]] = []
        for start, end, target in sorted(
            candidates, key=lambda item: (item[0], -(item[1] - item[0]))
        ):
            if any(
                start < chosen_end and end > chosen_start
                for chosen_start, chosen_end, _ in selected
            ):
                continue
            selected.append((start, end, target))

        terms: list[str] = []
        seen: set[str] = set()
        for _, _, target in sorted(selected):
            key = target.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append(target)
        return " ".join(terms)

    def _remember(self, query: str, result: SearchQueryTranslation) -> None:
        self._cache[query] = result
        self._cache.move_to_end(query)
        while len(self._cache) > MAX_CACHE_SIZE:
            self._cache.popitem(last=False)

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        return bool(CHINESE_RE.search(text))

    @staticmethod
    def _safe_preview(text: str, max_chars: int = 48) -> str:
        preview = " ".join(str(text).split())
        if len(preview) > max_chars:
            return preview[:max_chars] + "..."
        return preview
