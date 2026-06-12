"""Canned fallback responses for LLM failure scenarios -- Phase 3."""

from __future__ import annotations

CANNED_RU_TIMEOUT = (
    "Не удалось получить ответ из-за превышения времени ожидания. "
    "Рекомендую задать этот вопрос HR-специалисту."
)

CANNED_RU_TRANSLATE_FAILED = "Произошла ошибка перевода. Ответ предоставлен на русском языке."
