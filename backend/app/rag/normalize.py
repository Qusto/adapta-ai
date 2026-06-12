"""Нормализация ТОЛЬКО для эмбеддинга/матчинга, не для хранения/отображения."""

from __future__ import annotations

import unicodedata


def normalize_for_match(text: str) -> str:
    """Нормализация ТОЛЬКО для эмбеддинга/матчинга, не для хранения/отображения.

    Применяет NFKC-нормализацию, casefold и замену ё→е, чтобы
    "Журавлёво" и "журавлево" давали идентичный префикс при эмбеддинге.
    Возвращаемые тексты/метаданные не изменяются — нормализация только для вектора.
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.casefold()
    normalized = normalized.replace("ё", "е")  # ё → е (после casefold)
    return normalized
