"""Qwen client via OpenRouter — Phase 3 translate hi↔ru.

Uses openai Python SDK with base_url=OpenRouter.
Step A: hi→ru translate + intent extract (JSON output).
Step B: ru→hi translate (preserving [N] citation markers).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

_STEP_A_SYSTEM = (
    "You translate user questions from Hindi to Russian for a workplace assistant. "
    'Output JSON only: {"ru_query": "...", "intent": "schedule|location|payment|rules|other"}.'
)

# Канонизация русскоязычного запроса — перефразировка в стандартную форму для
# более стабильного эмбеддинг-поиска по корпусу документов.
_CANONICALIZE_RU_SYSTEM = (
    "Перефразируй вопрос работника на чистый, краткий русский для поиска по базе документов "
    "работодателя. Сохрани смысл. Output JSON only: {\"ru_query\": \"...\"}."
)

_STEP_B_SYSTEM = (
    "You translate Russian answers from a workplace assistant to Hindi. "
    "Preserve [1], [2], [3] citation markers exactly as-is. "
    "Output ONLY the Hindi translation."
)


class QwenClient:
    """Async Qwen 2.5 client via OpenRouter for hi↔ru translation."""

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._openai_client: AsyncOpenAI = AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": "https://adapta.demo",
                "X-Title": "AdaptaAI",
            },
        )

    async def translate_hi_to_ru(self, text: str) -> dict[str, str]:
        """Translate Hindi question to Russian + extract intent (Step A).

        Returns dict with keys: ru_query (str), intent (str).
        Falls back to original text as ru_query on JSON parse error.
        """
        response = await self._openai_client.chat.completions.create(
            model=self._settings.qwen_model,
            messages=[
                {"role": "system", "content": _STEP_A_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=256,
            stream=False,
        )
        raw_content: str = response.choices[0].message.content or ""
        try:
            result: dict[str, Any] = json.loads(raw_content)
            return {
                "ru_query": str(result.get("ru_query", text)),
                "intent": str(result.get("intent", "other")),
            }
        except (json.JSONDecodeError, KeyError):
            logger.warning(
                "QwenClient Step A: could not parse JSON response, using raw text as ru_query"
            )
            return {"ru_query": text, "intent": "other"}

    async def translate_ru_to_hi(self, text: str) -> str:
        """Translate Russian answer to Hindi (Step B).

        Preserves [1], [2], [3] citation markers in output.
        Returns the Hindi translation string.
        """
        response = await self._openai_client.chat.completions.create(
            model=self._settings.qwen_model,
            messages=[
                {"role": "system", "content": _STEP_B_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=512,
            stream=False,
        )
        result: str = response.choices[0].message.content or text
        return result

    async def translate_en_to_ru(self, text: str) -> dict[str, str]:
        """Translate English question to Russian + intent (mirror of hi Step A)."""
        system = (
            "You translate user questions from English to Russian for a workplace assistant. "
            'Output JSON only: {"ru_query": "...", "intent": "schedule|location|payment|rules|other"}.'
        )
        response = await self._openai_client.chat.completions.create(
            model=self._settings.qwen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=256,
            stream=False,
        )
        raw_content: str = response.choices[0].message.content or ""
        try:
            result: dict[str, Any] = json.loads(raw_content)
            return {
                "ru_query": str(result.get("ru_query", text)),
                "intent": str(result.get("intent", "other")),
            }
        except (json.JSONDecodeError, KeyError):
            logger.warning("QwenClient en→ru: JSON parse failed, using raw text")
            return {"ru_query": text, "intent": "other"}

    async def canonicalize_ru(self, text: str) -> dict[str, str]:
        """Канонизирует русский вопрос в стандартную форму для поиска (Step A для ru).

        Вызывает Qwen с temperature=0.0 и small max_tokens — дёшево и быстро.
        Возвращает dict с ключом ru_query.
        При ошибке парсинга JSON возвращает {"ru_query": text} (passthrough).
        """
        response = await self._openai_client.chat.completions.create(
            model=self._settings.qwen_model,
            messages=[
                {"role": "system", "content": _CANONICALIZE_RU_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=128,
            stream=False,
        )
        raw_content: str = response.choices[0].message.content or ""
        try:
            result: dict[str, Any] = json.loads(raw_content)
            return {"ru_query": str(result.get("ru_query", text))}
        except (json.JSONDecodeError, KeyError):
            logger.warning(
                "QwenClient canonicalize_ru: JSON parse failed, returning raw text"
            )
            return {"ru_query": text}

    async def translate_ru_to_en(self, text: str) -> str:
        """Translate Russian answer to English (mirror of Step B), preserving [N]."""
        system = (
            "You translate Russian answers from a workplace assistant to English. "
            "Preserve [1], [2], [3] citation markers exactly as-is. "
            "Output ONLY the English translation."
        )
        response = await self._openai_client.chat.completions.create(
            model=self._settings.qwen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=512,
            stream=False,
        )
        result: str = response.choices[0].message.content or text
        return result

    async def generate_answer(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> tuple[str, dict[str, int]]:
        """Generate SGR answer using Qwen (ablation eval, qwen_only mode).

        Accepts the same `messages` list as build_messages() produces —
        the full SGR system prompt + CONTEXT + VOPROS user turn.

        Args:
            messages: chat messages for the SGR prompt.
            model: optional model slug override (e.g. 'qwen/qwen3-235b-a22b').
                   When None, falls back to self._settings.qwen_model.

        Returns:
            (content, usage_dict) where content is the raw model output
            (suitable for parse_rag_answer) and usage_dict contains exact
            token counts from OpenRouter: {"prompt_tokens": N, "completion_tokens": M}.
            If response.usage is None (should not happen via OpenRouter), returns zeros.
        """
        effective_model = model or self._settings.qwen_model
        response = await self._openai_client.chat.completions.create(
            model=effective_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.2,
            max_tokens=512,
            stream=False,
        )
        content: str = response.choices[0].message.content or ""
        usage = response.usage
        if usage is not None:
            usage_dict: dict[str, int] = {
                "prompt_tokens": usage.prompt_tokens or 0,
                "completion_tokens": usage.completion_tokens or 0,
            }
        else:
            logger.warning("QwenClient.generate_answer: response.usage is None — returning zeros")
            usage_dict = {"prompt_tokens": 0, "completion_tokens": 0}
        return content, usage_dict
