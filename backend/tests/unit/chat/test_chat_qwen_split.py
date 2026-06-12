"""Unit tests for Phase 3 Qwen split logic — RED phase.

Tests-first items covered:
  4. test_chat_skips_qwen_when_language_is_ru
  5. test_chat_translates_hindi_via_qwen (calls Qwen twice: hi->ru and ru->hi)
  11. test_qwen_translate_failure_fallback_to_russian
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from tests.unit.chat.test_chat_streaming import parse_sse_body


pytestmark = pytest.mark.asyncio

DEVANAGARI_PATTERN = re.compile(r"[ऀ-ॿ]")


class TestChatQwenForRussian:
    """Tests for ru-path Qwen behaviour — updated after canonicalize_ru feature.

    PRD §3.2 latency-оптимизация пересмотрена: для ru в режиме "both"
    теперь вызывается canonicalize_ru (канонизация формулировки перед retrieval),
    но translate_* (hi↔ru) по-прежнему НЕ вызывается.
    """

    async def test_chat_calls_canonicalize_ru_for_russian(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
        mock_qwen: MagicMock,
    ) -> None:
        """Для language=ru в режиме 'both' должен вызываться canonicalize_ru."""
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = mock_qwen

            fake_user = MagicMock()
            fake_user.role = "migrant"
            fake_user.company_id = uuid.uuid4()
            fake_user.preferred_language = "ru"

            with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={"text": "Во сколько смена?", "language": "ru"},
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        # Для ru должен вызываться canonicalize_ru (Step A канонизация)
        mock_qwen.canonicalize_ru.assert_called_once()

        # Перевод hi↔ru по-прежнему НЕ вызывается для русских вопросов
        mock_qwen.translate_hi_to_ru.assert_not_called()
        mock_qwen.translate_ru_to_hi.assert_not_called()

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}"
        )

    async def test_chat_skips_translate_for_russian(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
        mock_qwen: MagicMock,
    ) -> None:
        """Для language=ru translate_hi_to_ru и translate_ru_to_hi НЕ вызываются.

        Проверяет, что Step B (ru→hi) не применяется к русскому ответу.
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = mock_qwen

            fake_user = MagicMock()
            fake_user.role = "migrant"
            fake_user.company_id = uuid.uuid4()
            fake_user.preferred_language = "ru"

            with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={"text": "Во сколько смена?", "language": "ru"},
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        mock_qwen.translate_hi_to_ru.assert_not_called()
        mock_qwen.translate_ru_to_hi.assert_not_called()

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}"
        )


class TestChatTranslatesHindiViaQwen:
    """test_chat_translates_hindi_via_qwen — Tests-first item 5."""

    async def test_chat_translates_hindi_via_qwen(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
        mock_qwen: MagicMock,
    ) -> None:
        """For language=hi, Qwen must be called twice: hi->ru (Step A) and ru->hi (Step B).

        Per PRD §3.4 translation pipeline:
          Step A: hi->ru (translate question)
          Step B: ru->hi (translate answer back)
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = mock_qwen

            fake_user = MagicMock()
            fake_user.role = "migrant"
            fake_user.company_id = uuid.uuid4()
            fake_user.preferred_language = "hi"

            with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={
                            "text": "मेरी शिफ्ट कब शुरू होती है?",
                            "language": "hi",
                        },
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:200]}"
        )

        # Verify Qwen was called twice
        mock_qwen.translate_hi_to_ru.assert_called_once()
        mock_qwen.translate_ru_to_hi.assert_called_once()

        # Step A arg should contain the Hindi question
        hi_to_ru_call_args = mock_qwen.translate_hi_to_ru.call_args
        assert hi_to_ru_call_args is not None, "translate_hi_to_ru must have been called"
        first_arg = hi_to_ru_call_args[0][0] if hi_to_ru_call_args[0] else (
            hi_to_ru_call_args[1].get("text") or hi_to_ru_call_args[1].get("query", "")
        )
        assert "शिफ्ट" in first_arg or "मेरी" in first_arg, (
            f"Step A must receive Hindi question, got: {first_arg!r}"
        )


class TestQwenTranslateFailureFallback:
    """test_qwen_translate_failure_fallback_to_russian — Tests-first item 11."""

    async def test_qwen_translate_failure_fallback_to_russian(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
        mock_qwen_step_b_error: MagicMock,
    ) -> None:
        """When Qwen Step B (ru->hi) fails with 5xx, SSE must contain:
        - event: error with code=TRANSLATE_FAILED
        - Russian tokens still streamed (fallback to ru answer)
        Response must NOT crash.
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat
            MockQwen.return_value = mock_qwen_step_b_error

            fake_user = MagicMock()
            fake_user.role = "migrant"
            fake_user.company_id = uuid.uuid4()
            fake_user.preferred_language = "hi"

            with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={
                            "text": "मेरी शिफ्ट कब शुरू होती है?",
                            "language": "hi",
                        },
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        assert response.status_code == 200, (
            f"Expected 200 (SSE), got {response.status_code}: {response.text[:200]}"
        )

        events = parse_sse_body(response.content)
        event_names = [n for n, _ in events]

        assert "error" in event_names, (
            "SSE must contain 'error' event when Qwen Step B fails"
        )

        error_events = [(n, d) for n, d in events if n == "error"]
        _, error_data = error_events[0]
        assert error_data.get("code") == "TRANSLATE_FAILED", (
            f"error code must be TRANSLATE_FAILED, got: {error_data.get('code')!r}"
        )

        # Russian tokens must still be present (fallback to Russian answer)
        token_events = [(n, d) for n, d in events if n == "token"]
        assert len(token_events) > 0, (
            "Russian fallback tokens must be streamed even after TRANSLATE_FAILED"
        )
