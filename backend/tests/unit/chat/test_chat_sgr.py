"""Unit tests for SGR pipeline integration in chat handler — Phase 3.5.

Covers:
* New SSE events: `answer`, `citations`, `meta`.
* Citation `document_name` is human-readable (Bug #2 from e2e 2026-05-26).
* Out-of-context question (is_answerable=False) flows through the pipeline.
* Reparser retry kicks in on first-pass JSON failure.
* Safe fallback when both parses fail.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.chat.conftest import FAKE_CHUNKS
from tests.unit.chat.test_chat_streaming import parse_sse_body

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunked(payload: str, parts: int = 4) -> list[str]:
    """Split `payload` into roughly `parts` token chunks."""
    n = max(1, len(payload) // parts)
    return [payload[i : i + n] for i in range(0, len(payload), n)]


async def _collect_sse(gen: AsyncIterator[str]) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    async for chunk in gen:
        out.extend(parse_sse_body(chunk.encode("utf-8")))
    return out


def _mock_gigachat_with_payload(payload: str) -> MagicMock:
    mock = MagicMock()
    tokens = _chunked(payload)

    async def _stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        for token in tokens:
            yield token
            await asyncio.sleep(0)

    mock.chat_stream = _stream
    return mock


def _mock_gigachat_alternating(payloads: list[str]) -> MagicMock:
    """Yield a different payload on each chat_stream call (call_count based)."""
    mock = MagicMock()
    state = {"call": 0}

    def _factory(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        idx = state["call"]
        state["call"] += 1
        payload = payloads[min(idx, len(payloads) - 1)]
        tokens = _chunked(payload)

        async def _stream() -> AsyncIterator[str]:
            for token in tokens:
                yield token
                await asyncio.sleep(0)

        return _stream()

    mock.chat_stream = _factory
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSgrAnswerEvent:
    """`event: answer` is emitted with parsed answer text."""

    async def test_emits_answer_event_with_parsed_text(self, env_vars: dict[str, str]) -> None:
        from app.chat.message_handler import stream_chat_response

        doc_id = "doc-sgr-001"
        payload = (
            '{"is_answerable": true,'
            ' "reasoning": "В чанке [1] прямо указано время начала смены — 8:00.",'
            ' "answer": "Смена начинается в 8:00 [1].",'
            ' "citations": [{'
            f' "document_id": "{doc_id}",'
            ' "document_title": "Регламент общежития ПИК",'
            ' "page_number": 3,'
            ' "snippet": "Смена начинается в 8:00. Завтрак до 7:30."'
            '}],'
            ' "confidence": "high"}'
        )

        mock_gigachat = _mock_gigachat_with_payload(payload)
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = FAKE_CHUNKS

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
            patch("app.chat.message_handler.get_store", return_value=MagicMock()),
            patch("app.chat.message_handler.get_embedder", return_value=MagicMock()),
            patch("app.chat.message_handler._persist_messages", new=AsyncMock()),
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = MagicMock()

            events = await _collect_sse(
                stream_chat_response(
                    user_id=uuid.uuid4(),
                    company_id=uuid.uuid4(),
                    question="Во сколько начинается смена?",
                    language="ru",
                )
            )

        answer_events = [d for n, d in events if n == "answer"]
        assert len(answer_events) == 1, f"Expected exactly 1 answer event, got {len(answer_events)}"
        assert answer_events[0]["text"] == "Смена начинается в 8:00 [1]."


class TestSgrMetaEvent:
    """`event: meta` exposes reasoning + confidence + is_answerable."""

    async def test_emits_meta_event_with_reasoning_and_confidence(
        self, env_vars: dict[str, str]
    ) -> None:
        from app.chat.message_handler import stream_chat_response

        payload = (
            '{"is_answerable": true,'
            ' "reasoning": "В чанке [1] есть прямой ответ на вопрос пользователя.",'
            ' "answer": "Смена в 8:00 [1].",'
            ' "citations": [{'
            ' "document_id": "doc-meta",'
            ' "document_title": "Регламент ПИК",'
            ' "page_number": 3,'
            ' "snippet": "Смена в 8:00. Завтрак до 7:30."'
            '}],'
            ' "confidence": "medium"}'
        )

        mock_gigachat = _mock_gigachat_with_payload(payload)
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = FAKE_CHUNKS

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
            patch("app.chat.message_handler.get_store", return_value=MagicMock()),
            patch("app.chat.message_handler.get_embedder", return_value=MagicMock()),
            patch("app.chat.message_handler._persist_messages", new=AsyncMock()),
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = MagicMock()

            events = await _collect_sse(
                stream_chat_response(
                    user_id=uuid.uuid4(),
                    company_id=uuid.uuid4(),
                    question="Во сколько начинается смена?",
                    language="ru",
                )
            )

        meta_events = [d for n, d in events if n == "meta"]
        assert len(meta_events) == 1
        m = meta_events[0]
        assert m["is_answerable"] is True
        assert m["confidence"] == "medium"
        assert "чанке" in m["reasoning"] or "контекст" in m["reasoning"].lower()


class TestCitationTitleIsHumanReadable:
    """Bug #2 fix: citation `document_name` is NOT a raw filename."""

    async def test_document_name_uses_title_not_filename(
        self, env_vars: dict[str, str]
    ) -> None:
        from app.chat.message_handler import stream_chat_response

        payload = (
            '{"is_answerable": true,'
            ' "reasoning": "Чанк [1] прямо отвечает на вопрос пользователя.",'
            ' "answer": "Смена в 8:00 [1].",'
            ' "citations": [{'
            ' "document_id": "doc-title-test",'
            ' "document_title": "Регламент общежития ПИК",'
            ' "page_number": 3,'
            ' "snippet": "Смена начинается в 8:00. Завтрак до 7:30."'
            '}],'
            ' "confidence": "high"}'
        )

        mock_gigachat = _mock_gigachat_with_payload(payload)
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = FAKE_CHUNKS

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
            patch("app.chat.message_handler.get_store", return_value=MagicMock()),
            patch("app.chat.message_handler.get_embedder", return_value=MagicMock()),
            patch("app.chat.message_handler._persist_messages", new=AsyncMock()),
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = MagicMock()

            events = await _collect_sse(
                stream_chat_response(
                    user_id=uuid.uuid4(),
                    company_id=uuid.uuid4(),
                    question="Во сколько смена?",
                    language="ru",
                )
            )

        citations_events = [d for n, d in events if n == "citations"]
        assert citations_events, "Must have citations event"
        first_citation = citations_events[0]["citations"][0]
        assert first_citation["document_name"] == "Регламент общежития ПИК"
        # Anti-regression: must NOT be the raw filename with .pdf
        assert not first_citation["document_name"].endswith(".pdf"), (
            f"document_name should be human title, got: {first_citation['document_name']!r}"
        )


class TestOutOfContextQuestion:
    """`is_answerable=False` end-to-end — no citations, low confidence.

    Since (B1): when LLM returns is_answerable=False the handler replaces the
    raw "N/A" string with no_info_answer(language) — a user-friendly localised
    message. The answer event must NOT contain "N/A".
    """

    async def test_unanswerable_question_emits_no_info_answer(
        self, env_vars: dict[str, str]
    ) -> None:
        from app.chat.router import no_info_answer

        from app.chat.message_handler import stream_chat_response

        payload = (
            '{"is_answerable": false,'
            ' "reasoning": "В контексте нет фактов про зарплату — ответить честно не могу.",'
            ' "answer": "N/A",'
            ' "citations": [],'
            ' "confidence": "low"}'
        )

        mock_gigachat = _mock_gigachat_with_payload(payload)
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = FAKE_CHUNKS

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
            patch("app.chat.message_handler.get_store", return_value=MagicMock()),
            patch("app.chat.message_handler.get_embedder", return_value=MagicMock()),
            patch("app.chat.message_handler._persist_messages", new=AsyncMock()),
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = MagicMock()

            events = await _collect_sse(
                stream_chat_response(
                    user_id=uuid.uuid4(),
                    company_id=uuid.uuid4(),
                    question="Какая зарплата на стройке?",
                    language="ru",
                )
            )

        meta_events = [d for n, d in events if n == "meta"]
        citations_events = [d for n, d in events if n == "citations"]
        answer_events = [d for n, d in events if n == "answer"]
        done_events = [d for n, d in events if n == "done"]

        assert meta_events, "Must have meta event"
        assert meta_events[0]["is_answerable"] is False
        assert citations_events[0]["citations"] == [], (
            "Citations must be empty when is_answerable=False"
        )
        # (B1): raw "N/A" is replaced with a user-friendly localised message.
        expected_text = no_info_answer("ru")
        assert answer_events[0]["text"] == expected_text, (
            f"Expected no_info_answer('ru'), got: {answer_events[0]['text']!r}"
        )
        assert answer_events[0]["text"] != "N/A", (
            "Raw 'N/A' must not be shown to the user — must be replaced with no_info_answer()"
        )
        assert done_events[0]["confidence"] == 0.0


class TestReparserRetrySuccess:
    """First GigaChat response is malformed → reparser retry succeeds."""

    async def test_reparser_recovers_from_first_failure(
        self, env_vars: dict[str, str]
    ) -> None:
        from app.chat.message_handler import stream_chat_response

        bad_first = "Сейчас отвечу: это не JSON."
        good_second = (
            '{"is_answerable": true,'
            ' "reasoning": "Чанк [1] напрямую отвечает на вопрос.",'
            ' "answer": "Смена начинается в 8:00 [1].",'
            ' "citations": [{'
            ' "document_id": "doc-reparse",'
            ' "document_title": "Регламент",'
            ' "page_number": 3,'
            ' "snippet": "Смена начинается в 8:00. Завтрак до 7:30."'
            '}],'
            ' "confidence": "high"}'
        )

        mock_gigachat = _mock_gigachat_alternating([bad_first, good_second])
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = FAKE_CHUNKS

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
            patch("app.chat.message_handler.get_store", return_value=MagicMock()),
            patch("app.chat.message_handler.get_embedder", return_value=MagicMock()),
            patch("app.chat.message_handler._persist_messages", new=AsyncMock()),
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = MagicMock()

            events = await _collect_sse(
                stream_chat_response(
                    user_id=uuid.uuid4(),
                    company_id=uuid.uuid4(),
                    question="Смена?",
                    language="ru",
                )
            )

        answer_events = [d for n, d in events if n == "answer"]
        meta_events = [d for n, d in events if n == "meta"]
        assert answer_events[0]["text"] == "Смена начинается в 8:00 [1]."
        assert meta_events[0]["is_answerable"] is True


class TestReparserDoubleFailureFallback:
    """Both attempts fail → safe fallback + SGR_PARSE_FAILED error event."""

    async def test_double_parse_failure_uses_safe_fallback(
        self, env_vars: dict[str, str]
    ) -> None:
        from app.chat.message_handler import stream_chat_response

        garbage = "это совсем не json, увы"
        mock_gigachat = _mock_gigachat_alternating([garbage, garbage])
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = FAKE_CHUNKS

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
            patch("app.chat.message_handler.get_store", return_value=MagicMock()),
            patch("app.chat.message_handler.get_embedder", return_value=MagicMock()),
            patch("app.chat.message_handler._persist_messages", new=AsyncMock()),
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = MagicMock()

            events = await _collect_sse(
                stream_chat_response(
                    user_id=uuid.uuid4(),
                    company_id=uuid.uuid4(),
                    question="Любой вопрос?",
                    language="ru",
                )
            )

        names = [n for n, _ in events]
        error_events = [d for n, d in events if n == "error"]
        answer_events = [d for n, d in events if n == "answer"]
        meta_events = [d for n, d in events if n == "meta"]

        assert "error" in names
        assert any(e["code"] == "SGR_PARSE_FAILED" for e in error_events)
        # Safe fallback text — user-friendly, not literal "N/A"
        assert answer_events[0]["text"] != "N/A"
        assert "попробуйте" in answer_events[0]["text"].lower()
        assert meta_events[0]["is_answerable"] is False
