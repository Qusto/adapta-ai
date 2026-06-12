"""Unit tests for app.rag.normalize — ё/регистр нормализация для эмбеддинга."""
from __future__ import annotations

import pytest

from app.rag.normalize import normalize_for_match


class TestNormalizeForMatch:
    def test_yo_replaced_with_ye(self) -> None:
        """'Журавлёво 2' → 'журавлево 2': ё заменяется на е, регистр снижается."""
        assert normalize_for_match("Журавлёво 2") == "журавлево 2"

    def test_yo_and_ye_produce_same_result(self) -> None:
        """'Журавлёво' и 'Журавлево' нормализуются одинаково."""
        assert normalize_for_match("Журавлёво") == normalize_for_match("Журавлево")

    def test_casefold(self) -> None:
        """Верхний регистр приводится к нижнему."""
        assert normalize_for_match("СМЕНА") == "смена"

    def test_nfkc_normalization(self) -> None:
        """NFKC разворачивает совместимые формы Unicode."""
        # Полная ширина 'Ａ' (U+FF21) → 'a'
        assert normalize_for_match("Ａ") == "a"

    def test_empty_string_returned_as_is(self) -> None:
        """Пустая строка возвращается без изменений."""
        assert normalize_for_match("") == ""

    def test_none_returned_as_is(self) -> None:
        """None возвращается без изменений."""
        assert normalize_for_match(None) is None  # type: ignore[arg-type]

    def test_uppercase_yo_after_casefold(self) -> None:
        """'Ё' (заглавная) после casefold → 'ё' → затем 'е'."""
        assert normalize_for_match("ЁЖ") == "еж"

    def test_mixed_language_unchanged_except_case(self) -> None:
        """Латиница/цифры не трогаются, кроме регистра."""
        assert normalize_for_match("Phase 2: Адаптация") == "phase 2: адаптация"
