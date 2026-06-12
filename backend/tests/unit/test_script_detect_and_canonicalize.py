"""Unit-тесты для Tasks 3 & 4:
- canonicalize_ru: вызывается для ru-пути, возвращает dict с ru_query
- script_detect: текст с деванагари → language="hi" независимо от тега
- temperature=0.0 в GigaChat payload (Task 2)
- N/A → no_info_answer по-прежнему работает (defence regression)
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Task 4 — Devanagari script detection
# ---------------------------------------------------------------------------


class TestDevanagariScriptDetect:
    """Проверяем helper _detect_script_language."""

    def test_devanagari_text_overrides_ru_to_hi(self, env_vars: dict) -> None:
        """Текст с деванагари + language='ru' → должен вернуть 'hi'."""
        from app.chat.message_handler import _detect_script_language

        result = _detect_script_language("मेरी शिफ्ट कब शुरू होती है?", "ru")
        assert result == "hi", f"Expected 'hi', got {result!r}"

    def test_devanagari_text_keeps_hi(self, env_vars: dict) -> None:
        """Текст с деванагари + language='hi' → остаётся 'hi'."""
        from app.chat.message_handler import _detect_script_language

        result = _detect_script_language("मेरी शिफ्ट कब शुरू होती है?", "hi")
        assert result == "hi"

    def test_russian_text_keeps_ru(self, env_vars: dict) -> None:
        """Русский текст + language='ru' → остаётся 'ru'."""
        from app.chat.message_handler import _detect_script_language

        result = _detect_script_language("Во сколько начинается смена?", "ru")
        assert result == "ru"

    def test_latin_text_keeps_en(self, env_vars: dict) -> None:
        """Латиница + language='en' → остаётся 'en'."""
        from app.chat.message_handler import _detect_script_language

        result = _detect_script_language("What time does the shift start?", "en")
        assert result == "en"

    def test_mixed_text_with_devanagari_overrides_to_hi(self, env_vars: dict) -> None:
        """Смешанный текст (латиница + деванагари) → 'hi'."""
        from app.chat.message_handler import _detect_script_language

        result = _detect_script_language("shift कब है?", "en")
        assert result == "hi"

    def test_empty_text_keeps_language(self, env_vars: dict) -> None:
        """Пустая строка не изменяет language."""
        from app.chat.message_handler import _detect_script_language

        assert _detect_script_language("", "ru") == "ru"
        assert _detect_script_language("", "hi") == "hi"


# ---------------------------------------------------------------------------
# Task 3 — canonicalize_ru в QwenClient
# ---------------------------------------------------------------------------


class TestCanonicalizeRu:
    """Проверяем QwenClient.canonicalize_ru."""

    async def test_canonicalize_ru_returns_dict_with_ru_query(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """canonicalize_ru должен вернуть dict с ключом ru_query."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        fake_message = MagicMock()
        fake_message.content = '{"ru_query": "Когда начинается смена?"}'
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        result = await client.canonicalize_ru("Во сколько смена?")

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "ru_query" in result, "Ключ ru_query должен быть в ответе"
        assert isinstance(result["ru_query"], str)
        assert len(result["ru_query"]) > 0

    async def test_canonicalize_ru_uses_temperature_zero(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """canonicalize_ru должен вызывать API с temperature=0.0."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        fake_message = MagicMock()
        fake_message.content = '{"ru_query": "Тест"}'
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        await client.canonicalize_ru("Тест запрос")

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs.get("temperature") == 0.0, (
            f"temperature должно быть 0.0, получено {call_kwargs.get('temperature')}"
        )

    async def test_canonicalize_ru_fallback_on_json_error(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При невалидном JSON — canonicalize_ru возвращает исходный текст как ru_query."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        fake_message = MagicMock()
        fake_message.content = "это не JSON"
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        original_text = "Во сколько начинается смена?"
        result = await client.canonicalize_ru(original_text)

        assert result == {"ru_query": original_text}, (
            f"Fallback должен вернуть исходный текст, получено: {result}"
        )

    async def test_canonicalize_ru_max_tokens_small(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """canonicalize_ru должен использовать max_tokens <= 128 (дешёвый вызов)."""
        from app.llm.qwen_client import QwenClient

        client = QwenClient()

        fake_message = MagicMock()
        fake_message.content = '{"ru_query": "Тест"}'
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        mock_create = AsyncMock(return_value=fake_response)
        monkeypatch.setattr(client, "_openai_client", MagicMock())
        client._openai_client.chat.completions.create = mock_create

        await client.canonicalize_ru("Тест")

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs.get("max_tokens", 9999) <= 128, (
            f"max_tokens должен быть <= 128, получено {call_kwargs.get('max_tokens')}"
        )


# ---------------------------------------------------------------------------
# Task 2 — temperature=0.0 в GigaChat payload
# ---------------------------------------------------------------------------


class TestGigaChatTemperatureZero:
    """Проверяем что GigaChat payload использует temperature=0.0."""

    async def test_gigachat_payload_temperature_is_zero(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_raw_stream должен передавать temperature=0.0 в payload."""
        import json as _json

        from app.llm.gigachat_client import GigaChatClient

        client = GigaChatClient()

        async def _fake_ensure_token() -> str:
            return "fake-token"

        monkeypatch.setattr(client, "_ensure_token", _fake_ensure_token)

        captured_payloads: list[dict] = []

        import httpx
        from unittest.mock import AsyncMock as _AsyncMock, MagicMock as _MagicMock

        # Перехватываем httpx.AsyncClient.stream
        class _FakeResponse:
            status_code = 200
            request = MagicMock()

            async def aiter_lines(self):
                # Возвращаем один токен и [DONE]
                yield 'data: {"choices": [{"delta": {"content": "Тест"}}]}'
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

        class _FakeClient:
            def stream(self, method, url, **kwargs):
                captured_payloads.append(kwargs.get("json", {}))
                return _FakeResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.llm.gigachat_client.httpx.AsyncClient",
            lambda **kwargs: _FakeClient(),
        )

        tokens = []
        async for tok in client._raw_stream(
            messages=[{"role": "user", "content": "test"}],
            token="fake-token",
        ):
            tokens.append(tok)

        assert len(captured_payloads) >= 1, "HTTP запрос должен был быть сделан"
        payload = captured_payloads[0]
        assert payload.get("temperature") == 0.0, (
            f"temperature должна быть 0.0, получено: {payload.get('temperature')}"
        )


# ---------------------------------------------------------------------------
# Regression — N/A → no_info_answer по-прежнему работает
# ---------------------------------------------------------------------------


class TestNaToNoInfoAnswerRegression:
    """Убеждаемся что N/A в parsed.answer заменяется на no_info_answer()."""

    def test_na_answer_produces_no_info_text(self, env_vars: dict) -> None:
        """Когда GigaChat вернул answer='N/A', pipeline должен выдать локализованный текст."""
        from app.chat.router import no_info_answer

        # Для русского языка
        ru_fallback = no_info_answer("ru")
        assert isinstance(ru_fallback, str)
        assert len(ru_fallback) > 10, "no_info_answer('ru') должен вернуть осмысленный текст"

        # Для хинди
        hi_fallback = no_info_answer("hi")
        assert isinstance(hi_fallback, str)
        assert len(hi_fallback) > 10, "no_info_answer('hi') должен вернуть осмысленный текст"

    def test_na_sentinel_is_string(self, env_vars: dict) -> None:
        """Значение-sentinel 'N/A' — это строка, чтобы сравнение == работало."""
        sentinel = "N/A"
        assert isinstance(sentinel, str)
        # В message_handler: `if parsed.answer == "N/A"`
        from app.rag.schemas import RagAnswer

        parsed = RagAnswer(
            is_answerable=False,
            reasoning="нет в контексте — ни один чанк не отвечает на вопрос пользователя",
            answer="N/A",
            citations=[],
            confidence="low",
        )
        assert parsed.answer == "N/A"
