"""Phase 10 (WS-F) — intent router for the chat pipeline (variant D).

Cheap, deterministic pre-filter that runs BEFORE retrieval. Catches obvious
non-questions (greetings, thanks, "test", gibberish) and answers them directly
in the user's language — so off-topic input no longer produces an embarrassing
"N/A · not found · 0% confidence" RAG miss. Anything substantive falls through
to RAG (bias-to-RAG on uncertainty: we never drop a real question).

Emergencies are handled earlier by the keyword detector (not here).
Multilingual by design (ru/hi/en) — works on the original text, so no extra
LLM round-trip and fully unit-testable.
"""

from __future__ import annotations

import os
import re

INTENT_GREETING = "greeting"
INTENT_THANKS = "thanks"
INTENT_SMALLTALK = "smalltalk"  # test/gibberish/empty — no real question
INTENT_DOMAIN = "domain"        # → RAG

# Intents that get a direct canned answer (skip RAG + product card).
DIRECT_INTENTS = frozenset({INTENT_GREETING, INTENT_THANKS, INTENT_SMALLTALK})

_GREETING = {
    "привет", "здравствуй", "здравствуйте", "добрый день", "доброе утро",
    "добрый вечер", "хай", "hello", "hi", "hey", "hii", "good morning",
    "good evening", "namaste", "नमस्ते", "नमस्कार", "सलाम", "salaam", "salam",
}
_THANKS = {
    "спасибо", "благодарю", "спс", "thanks", "thank you", "thx", "ty",
    "धन्यवाद", "शुक्रिया", "thank", "thankyou",
}
# Explicit no-content tokens.
_NOISE = {
    "test", "тест", "проверка", "ok", "ок", "окей", "okay", "ping", "пинг",
    "...", "hmm", "хм", "asdf", "qwerty", "123", "."
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)  # unicode letters only


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def classify(text: str) -> str:
    """Return an intent. Conservative: defaults to DOMAIN (→ RAG) when unsure."""
    t = _norm(text)
    if not t:
        return INTENT_SMALLTALK

    # Strip trailing punctuation for exact-match checks.
    stripped = t.strip(" .!?,…")

    if stripped in _GREETING:
        return INTENT_GREETING
    if stripped in _THANKS:
        return INTENT_THANKS
    if stripped in _NOISE:
        return INTENT_SMALLTALK

    words = _WORD_RE.findall(t)
    # No letters at all (pure digits/punct/emoji) → smalltalk.
    if not words:
        return INTENT_SMALLTALK
    # Single very short token, not a question → smalltalk (e.g. "test", "ок").
    if len(words) == 1 and len(words[0]) <= 3 and "?" not in t:
        return INTENT_SMALLTALK
    # Leading greeting word on a short utterance with no question → greeting.
    if words[0] in _GREETING and len(words) <= 2 and "?" not in t:
        return INTENT_GREETING

    # Everything else is treated as a real question → RAG (bias-to-RAG).
    return INTENT_DOMAIN


# Canned, language-correct replies. Steer the user toward a real question.
_DIRECT_ANSWERS: dict[str, dict[str, str]] = {
    INTENT_GREETING: {
        "ru": "Здравствуйте! Я — AI-помощник. Спросите про работу, документы или жизнь в России — например, про патент, СНИЛС или общежитие.",
        "hi": "नमस्ते! मैं आपका AI सहायक हूँ। काम, दस्तावेज़ या रूस में जीवन के बारे में पूछें — जैसे पेटेंट, SNILS या छात्रावास।",
        "en": "Hello! I'm your AI assistant. Ask about work, documents or life in Russia — for example, the work patent, SNILS or the dormitory.",
    },
    INTENT_THANKS: {
        "ru": "Пожалуйста! Если появятся вопросы про работу или документы — спрашивайте в любое время.",
        "hi": "आपका स्वागत है! काम या दस्तावेज़ों के बारे में कोई भी सवाल हो — कभी भी पूछें।",
        "en": "You're welcome! Whenever you have a question about work or documents, just ask.",
    },
    INTENT_SMALLTALK: {
        "ru": "Я помогаю с работой и жизнью в России. Задайте вопрос — например: «Когда зарплата?», «Как продлить патент?», «Где находится общежитие?».",
        "hi": "मैं रूस में काम और जीवन में मदद करता हूँ। एक सवाल पूछें — जैसे: «वेतन कब मिलेगा?», «पेटेंट कैसे बढ़ाएँ?», «छात्रावास कहाँ है?».",
        "en": "I help with work and life in Russia. Ask a question — e.g. \"When is payday?\", \"How do I renew the patent?\", \"Where is the dormitory?\".",
    },
}


def direct_answer(intent: str, language: str) -> str:
    """Localized canned reply for a non-domain intent. Falls back ru→en."""
    lang = language if language in ("ru", "hi", "en") else "ru"
    table = _DIRECT_ANSWERS.get(intent, _DIRECT_ANSWERS[INTENT_SMALLTALK])
    return table.get(lang) or table["ru"]


# ---------------------------------------------------------------------------
# Retrieval-score gating (corpus-awareness via embeddings)
# ---------------------------------------------------------------------------

#: Minimum top-1 employer-doc similarity to treat a question as "in our corpus".
#: Below this we don't force the LLM to answer from weak evidence — we return a
#: graceful "no info yet" and escalate to HR.
#:
#: DEFAULT 0.785 — CALIBRATED on the prod corpus 2026-06-01 (multilingual-e5,
#: compressed range): in-corpus work-schedule/construction questions scored
#: 0.791–0.836; out-of-corpus (dormitory 0.778, food 0.761) scored ≤0.778.
#: 0.785 sits in the clean gap → gates out-of-corpus, passes in-corpus.
#: Override via ADAPTA_RAG_SCORE_GATE; set 0.0 to disable. Re-calibrate if the
#: document corpus changes materially.
def rag_score_gate() -> float:
    try:
        return float(os.getenv("ADAPTA_RAG_SCORE_GATE", "0.785"))
    except ValueError:
        return 0.785


_NO_INFO: dict[str, str] = {
    "ru": "По этому вопросу у меня пока нет информации в базе работодателя — я передал его вашему HR, он ответит. А пока могу помочь с темами: общежитие, патент и документы, зарплата, ДМС, жизнь в России.",
    "hi": "इस सवाल पर अभी मेरे पास नियोक्ता डेटाबेस में जानकारी नहीं है — मैंने इसे आपके HR को भेज दिया है, वे जवाब देंगे। तब तक मैं इन विषयों में मदद कर सकता हूँ: छात्रावास, पेटेंट और दस्तावेज़, वेतन, DMS, रूस में जीवन।",
    "en": "I don't have information on this in the employer's knowledge base yet — I've passed it to your HR, who will reply. Meanwhile I can help with: dormitory, work patent and documents, salary, DMS, life in Russia.",
}


def no_info_answer(language: str) -> str:
    """Localized graceful fallback when the question is outside the corpus."""
    lang = language if language in ("ru", "hi", "en") else "ru"
    return _NO_INFO.get(lang) or _NO_INFO["ru"]
