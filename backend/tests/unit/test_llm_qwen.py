"""Unit tests for app.llm.qwen_client.QwenClient — Phase 3 (RED).

Tests-first items from 03_chat.md:
  7. test_qwen_translates_hindi_to_russian
  8. test_qwen_translates_russian_answer_to_hindi
  9. (skips_qwen covered in chat streaming tests)
"""

from __future__ import annotations

import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio

HINDI_QUESTION = "मेरी शिफ्ट कब शुरू होती है?"
RUSSIAN_ANSWER_WITH_CITATION = "Смена начинается в 8:00 [1]."
DEVANAGARI_PATTERN = re.compile(r"[ऀ-ॿ]")


class TestQwenClientImport:
    """Verify module structure before any calls (ImportError = red)."""

    def test_qwen_client_importable(self, env_vars: dict) -> None:
        """QwenClient must be importable from app.llm.qwen_client."""
        from app.llm.qwen_client import QwenClient  # noqa: F401

    def test_qwen_client_has_translate_hi_to_ru(self, env_vars: dict) -> None:
        """QwenClient must have translate_hi_to_ru method."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()
        assert hasattr(client, "translate_hi_to_ru"), (
            "QwenClient must expose translate_hi_to_ru"
        )

    def test_qwen_client_has_translate_ru_to_hi(self, env_vars: dict) -> None:
        """QwenClient must have translate_ru_to_hi method."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()
        assert hasattr(client, "translate_ru_to_hi"), (
            "QwenClient must expose translate_ru_to_hi"
        )


class TestQwenTranslateHindiToRussian:
    """test_qwen_translates_hindi_to_russian (Tests-first item 7)."""

    async def test_qwen_translates_hindi_to_russian(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """translate_hi_to_ru returns dict with ru_query (str) and intent (str).

        Step A per PRD §3.4: output JSON {"ru_query": "...", "intent": "..."}
        """
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        # Monkeypatch the OpenAI async client call
        fake_message = MagicMock()
        fake_message.content = '{"ru_query": "Когда начинается моя смена?", "intent": "schedule"}'
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        result = await client.translate_hi_to_ru(HINDI_QUESTION)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "ru_query" in result, "Result must have 'ru_query' key"
        assert "intent" in result, "Result must have 'intent' key"
        assert isinstance(result["ru_query"], str), "ru_query must be str"
        assert isinstance(result["intent"], str), "intent must be str"
        assert len(result["ru_query"]) > 0, "ru_query must be non-empty"

    async def test_qwen_translate_hi_to_ru_calls_openrouter(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """translate_hi_to_ru must invoke the OpenAI-compatible client once."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        fake_message = MagicMock()
        fake_message.content = '{"ru_query": "Тест", "intent": "other"}'
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        await client.translate_hi_to_ru(HINDI_QUESTION)

        mock_create.assert_called_once()


class TestQwenTranslateRussianToHindi:
    """test_qwen_translates_russian_answer_to_hindi (Tests-first item 8)."""

    async def test_qwen_translates_russian_answer_to_hindi(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """translate_ru_to_hi returns a string containing devanagari characters.

        Per PRD §3.4 Step B: output ONLY the Hindi translation, preserving [1] markers.
        """
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        # Hindi answer that includes devanagari + preserved citation marker
        hindi_text = "पाली 8:00 बजे शुरू होती है [1]."

        fake_message = MagicMock()
        fake_message.content = hindi_text
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        result = await client.translate_ru_to_hi(RUSSIAN_ANSWER_WITH_CITATION)

        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert DEVANAGARI_PATTERN.search(result), (
            "Result must contain Devanagari characters (Hindi script)"
        )

    async def test_qwen_translate_ru_to_hi_preserves_citation_markers(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Citation markers [1], [2] must be preserved in the Hindi output."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        hindi_with_markers = "पाली 8:00 बजे शुरू होती है [1]। नाश्ता 7:30 तक है [2]।"

        fake_message = MagicMock()
        fake_message.content = hindi_with_markers
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        result = await client.translate_ru_to_hi(
            "Смена начинается в 8:00 [1]. Завтрак до 7:30 [2]."
        )

        assert "[1]" in result, "Citation marker [1] must be preserved in Hindi output"
        assert "[2]" in result, "Citation marker [2] must be preserved in Hindi output"
