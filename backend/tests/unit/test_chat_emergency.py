"""Unit tests for emergency-detection short-circuit.

Tests the _is_emergency detector function directly — no DB, no SSE, no LLM.
Imports are deferred inside test functions so env_vars fixture runs first.
"""

from __future__ import annotations

import pytest


class TestIsEmergencyDetectsRuKeywords:
    """test_is_emergency_detects_ru_keywords."""

    @pytest.mark.parametrize(
        "text",
        [
            "я упал на стройке, кажется сломал ногу",
            "вызовите скорую! человеку плохо",
            "пожар на объекте, горит склад",
            "у меня кровотечение, помогите",
            "человек потерял сознание, нужна скорая помощь",
            "авария на линии, есть пострадавшие",
            "удар током, электротравма",
            "коллега умирает, что делать",
            "позвоните 112 пожалуйста",
            "я задыхаюсь",
            "у меня кровь идёт",
        ],
    )
    def test_detects_ru_emergency(self, env_vars: dict[str, str], text: str) -> None:
        from app.chat.message_handler import _is_emergency  # noqa: PLC0415

        assert _is_emergency(text, "ru") is True, (
            f"Expected emergency detected for: {text!r}"
        )

    def test_detects_uppercase_normalized(self, env_vars: dict[str, str]) -> None:
        from app.chat.message_handler import _is_emergency  # noqa: PLC0415

        assert _is_emergency("ПОЖАР НА ОБЪЕКТЕ", "ru") is True

    def test_detects_mixed_case(self, env_vars: dict[str, str]) -> None:
        from app.chat.message_handler import _is_emergency  # noqa: PLC0415

        assert _is_emergency("Вызовите Скорую Помощь", "ru") is True


class TestIsEmergencyNoFalsePositive:
    """test_is_emergency_no_false_positive — normal migrant questions should NOT trigger."""

    @pytest.mark.parametrize(
        "text",
        [
            "когда зарплата?",
            "как звонить домой?",
            "во сколько начинается смена?",
            "где столовая?",
            "как оформить отпуск?",
            "где получить медполис?",
            "сколько стоит проезд на автобусе?",
            "как перевести деньги на родину?",
            "какой график работы на следующей неделе?",
            "где взять аванс?",
        ],
    )
    def test_no_false_positive(self, env_vars: dict[str, str], text: str) -> None:
        from app.chat.message_handler import _is_emergency  # noqa: PLC0415

        assert _is_emergency(text, "ru") is False, (
            f"False positive: emergency wrongly detected for: {text!r}"
        )


class TestIsEmergencyHindi:
    """test_is_emergency_hindi — Hindi keyword detection."""

    @pytest.mark.parametrize(
        "text,lang",
        [
            ("दुर्घटना हो गई है", "hi"),
            ("मदद करो, चोट लगी है", "hi"),
            ("एम्बुलेंस बुलाओ", "hi"),
            ("खून बह रहा है", "hi"),
            ("वह बेहोश हो गया", "hi"),
            ("आग लगी है", "hi"),
            # code-switching: Hindi speaker uses RU emergency phrase
            ("कृपया вызовите скорую помощь", "hi"),
        ],
    )
    def test_detects_hindi_emergency(
        self, env_vars: dict[str, str], text: str, lang: str
    ) -> None:
        from app.chat.message_handler import _is_emergency  # noqa: PLC0415

        assert _is_emergency(text, lang) is True, (
            f"Expected emergency detected for Hindi text: {text!r}"
        )

    def test_hindi_no_false_positive(self, env_vars: dict[str, str]) -> None:
        from app.chat.message_handler import _is_emergency  # noqa: PLC0415

        assert _is_emergency("वेतन कब मिलेगा?", "hi") is False
        assert _is_emergency("काम का समय क्या है?", "hi") is False
