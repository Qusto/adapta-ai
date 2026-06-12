"""WS-F — intent router classification + localized direct answers.

Emulates the routing decision for representative chat inputs (the verification
the demo needs: greetings/test/gibberish must NOT hit RAG; real questions must).
"""

from __future__ import annotations

import pytest

from app.chat.router import (
    DIRECT_INTENTS,
    INTENT_DOMAIN,
    INTENT_GREETING,
    INTENT_SMALLTALK,
    INTENT_THANKS,
    classify,
    direct_answer,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        # Greetings (ru/en/hi)
        ("привет", INTENT_GREETING),
        ("Здравствуйте!", INTENT_GREETING),
        ("hello", INTENT_GREETING),
        ("Hi", INTENT_GREETING),
        ("नमस्ते", INTENT_GREETING),
        # Thanks
        ("спасибо", INTENT_THANKS),
        ("thanks", INTENT_THANKS),
        ("धन्यवाद", INTENT_THANKS),
        # Smalltalk / noise — the demo "test" case
        ("test", INTENT_SMALLTALK),
        ("тест", INTENT_SMALLTALK),
        ("ok", INTENT_SMALLTALK),
        ("123", INTENT_SMALLTALK),
        ("...", INTENT_SMALLTALK),
        ("", INTENT_SMALLTALK),
        # Real domain questions → RAG (must NOT be short-circuited)
        ("Когда зарплата?", INTENT_DOMAIN),
        ("Как продлить патент?", INTENT_DOMAIN),
        ("Where is the dormitory?", INTENT_DOMAIN),
        ("मुझे SNILS कहाँ मिलेगा?", INTENT_DOMAIN),
        ("Расскажи про ДМС полис", INTENT_DOMAIN),
        # Borderline: greeting word but with a real question → DOMAIN (bias-to-RAG)
        ("привет, когда зарплата?", INTENT_DOMAIN),
    ],
)
def test_classify(text, expected) -> None:  # noqa: ANN001
    assert classify(text) == expected


def test_direct_intents_membership() -> None:
    assert INTENT_GREETING in DIRECT_INTENTS
    assert INTENT_THANKS in DIRECT_INTENTS
    assert INTENT_SMALLTALK in DIRECT_INTENTS
    assert INTENT_DOMAIN not in DIRECT_INTENTS


@pytest.mark.parametrize("lang", ["ru", "hi", "en"])
def test_direct_answer_localized(lang) -> None:  # noqa: ANN001
    for intent in (INTENT_GREETING, INTENT_THANKS, INTENT_SMALLTALK):
        ans = direct_answer(intent, lang)
        assert ans and isinstance(ans, str)


def test_direct_answer_unknown_lang_falls_back_ru() -> None:
    # uz not supported yet → falls back to ru text (non-empty)
    assert direct_answer(INTENT_GREETING, "uz")
