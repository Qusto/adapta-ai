"""Unit tests for _severity() in chat_escalations.

Covers the is_emergency-based severity routing logic:
  - is_emergency=True → critical/emergency  (ONLY path to critical)
  - escalate=True, is_emergency=False, is_answerable=False → high/unanswerable
    (out-of-corpus HR-ticket: передано HR, but NOT ЭКСТРЕННО)
  - unanswerable, any language → high/unanswerable  (NOT critical)
  - low confidence → high/low_confidence
  - fallback → medium/low_confidence

Imports are deferred inside test functions so env_vars fixture runs first
(module-level import triggers the full app config chain which needs env vars).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Emergency path — only is_emergency=True reaches critical
# ---------------------------------------------------------------------------

class TestSeverityEmergencyPath:
    """is_emergency=True is the sole source of critical/emergency."""

    def test_is_emergency_true_gives_critical_emergency(self, env_vars: dict[str, str]) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(
            "hi", is_answerable=False, confidence=None,
            escalate=True, is_emergency=True,
        )
        assert sev == "critical"
        assert reason == "emergency"

    def test_is_emergency_true_overrides_confidence(self, env_vars: dict[str, str]) -> None:
        """Even low confidence does not override is_emergency=True."""
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(
            "ru", is_answerable=True, confidence=0.10,
            escalate=True, is_emergency=True,
        )
        assert sev == "critical"
        assert reason == "emergency"

    @pytest.mark.parametrize("lang", ["hi", "uz", "tg", "ky", "kk", "az", "ru", "en"])
    def test_is_emergency_true_all_langs(self, env_vars: dict[str, str], lang: str) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(
            lang, is_answerable=False, confidence=None,
            escalate=True, is_emergency=True,
        )
        assert sev == "critical", f"Expected critical for lang={lang!r}"
        assert reason == "emergency", f"Expected emergency for lang={lang!r}"

    def test_escalate_true_without_is_emergency_is_NOT_critical(
        self, env_vars: dict[str, str]
    ) -> None:
        """escalate=True alone (out-of-corpus HR-ticket) must NOT produce critical.

        This is the core regression guard: out-of-corpus gate sets escalate=True,
        is_emergency=False. The result must be high/unanswerable, not critical/emergency.
        """
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(
            "hi", is_answerable=False, confidence=None,
            escalate=True, is_emergency=False,
        )
        assert sev == "high", (
            "escalate=True with is_emergency=False must be high, not critical "
            "(out-of-corpus HR-ticket must not show ЭКСТРЕННО)"
        )
        assert reason == "unanswerable"

    def test_escalate_true_answerable_without_is_emergency_is_medium(
        self, env_vars: dict[str, str]
    ) -> None:
        """escalate=True, is_answerable=True, is_emergency=False → medium."""
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(
            "ru", is_answerable=True, confidence=0.90,
            escalate=True, is_emergency=False,
        )
        assert sev == "medium"
        assert reason == "low_confidence"


# ---------------------------------------------------------------------------
# Out-of-corpus path — escalate=True, is_emergency=False → high/unanswerable
# ---------------------------------------------------------------------------

class TestSeverityOutOfCorpus:
    """Out-of-corpus HR-ticket: escalate=True, is_emergency=False, is_answerable=False."""

    def test_out_of_corpus_is_high_unanswerable(self, env_vars: dict[str, str]) -> None:
        """Core contract: out-of-corpus gate → high/unanswerable, НЕ emergency."""
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(
            "ru", is_answerable=False, confidence=None,
            escalate=True, is_emergency=False,
        )
        assert sev == "high"
        assert reason == "unanswerable"

    @pytest.mark.parametrize("lang", ["hi", "uz", "tg", "ky", "kk", "az", "ru", "en"])
    def test_out_of_corpus_all_langs_high_unanswerable(
        self, env_vars: dict[str, str], lang: str
    ) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(
            lang, is_answerable=False, confidence=None,
            escalate=True, is_emergency=False,
        )
        assert sev == "high", (
            f"lang={lang!r}: out-of-corpus must be 'high', got {sev!r}"
        )
        assert reason == "unanswerable"


# ---------------------------------------------------------------------------
# Unanswerable — always high, never critical (language-blind)
# ---------------------------------------------------------------------------

class TestSeverityUnanswerable:
    """Out-of-corpus / unanswerable must map to high/unanswerable for ALL languages."""

    @pytest.mark.parametrize("lang", ["hi", "uz", "tg", "ky", "kk", "az", "ru", "en"])
    def test_unanswerable_no_is_emergency_is_high_not_critical(
        self, env_vars: dict[str, str], lang: str
    ) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity(lang, is_answerable=False, confidence=None, escalate=False)
        assert sev == "high", (
            f"lang={lang!r}: expected 'high', got {sev!r} — "
            "unanswerable must never be critical without is_emergency=True"
        )
        assert reason == "unanswerable"

    def test_unanswerable_with_none_confidence_is_high(self, env_vars: dict[str, str]) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("hi", is_answerable=False, confidence=None)
        assert sev == "high"
        assert reason == "unanswerable"

    def test_unanswerable_with_mid_confidence_is_high(self, env_vars: dict[str, str]) -> None:
        """Confidence above threshold but is_answerable=False → still high/unanswerable."""
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("uz", is_answerable=False, confidence=0.60)
        assert sev == "high"
        assert reason == "unanswerable"

    def test_hindi_unanswerable_no_is_emergency_is_high(self, env_vars: dict[str, str]) -> None:
        """Regression: must return high, not critical, for hi+unanswerable without is_emergency."""
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("hi", is_answerable=False, confidence=None, escalate=False)
        assert sev == "high", "hi unanswerable without is_emergency must be high, not critical"
        assert reason == "unanswerable"

    def test_uzbek_unanswerable_no_is_emergency_is_high(self, env_vars: dict[str, str]) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("uz", is_answerable=False, confidence=None, escalate=False)
        assert sev == "high"
        assert reason == "unanswerable"

    def test_tajik_unanswerable_no_is_emergency_is_high(self, env_vars: dict[str, str]) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("tg", is_answerable=False, confidence=None, escalate=False)
        assert sev == "high"
        assert reason == "unanswerable"


# ---------------------------------------------------------------------------
# Low confidence path
# ---------------------------------------------------------------------------

class TestSeverityLowConfidence:
    """Confidence at or below _LOW_CONFIDENCE_THRESHOLD with is_answerable=True."""

    def test_low_confidence_exactly_at_threshold_is_high(self, env_vars: dict[str, str]) -> None:
        # _LOW_CONFIDENCE_THRESHOLD = 0.35
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("ru", is_answerable=True, confidence=0.35)
        assert sev == "high"
        assert reason == "low_confidence"

    def test_low_confidence_below_threshold_is_high(self, env_vars: dict[str, str]) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("ru", is_answerable=True, confidence=0.10)
        assert sev == "high"
        assert reason == "low_confidence"

    def test_low_confidence_zero_is_high(self, env_vars: dict[str, str]) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("hi", is_answerable=True, confidence=0.0)
        assert sev == "high"
        assert reason == "low_confidence"

    def test_unanswerable_with_low_confidence_is_unanswerable(
        self, env_vars: dict[str, str]
    ) -> None:
        """is_answerable=False takes priority over low confidence; result is high/unanswerable.

        Note: new priority order is unanswerable BEFORE low_confidence.
        """
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("hi", is_answerable=False, confidence=0.20)
        assert sev == "high"
        assert reason == "unanswerable"


# ---------------------------------------------------------------------------
# Fallback / medium path
# ---------------------------------------------------------------------------

class TestSeverityMediumFallback:
    """Answerable, confidence above threshold, no is_emergency → medium."""

    def test_answerable_high_confidence_is_medium(self, env_vars: dict[str, str]) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("ru", is_answerable=True, confidence=0.90)
        assert sev == "medium"
        assert reason == "low_confidence"

    def test_answerable_none_confidence_is_medium(self, env_vars: dict[str, str]) -> None:
        """None confidence with is_answerable=True falls to medium/low_confidence."""
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("ru", is_answerable=True, confidence=None)
        assert sev == "medium"
        assert reason == "low_confidence"

    def test_answerable_above_threshold_confidence_is_medium(
        self, env_vars: dict[str, str]
    ) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev, reason = _severity("en", is_answerable=True, confidence=0.36)
        assert sev == "medium"
        assert reason == "low_confidence"


# ---------------------------------------------------------------------------
# Language parameter is ignored (language-blind)
# ---------------------------------------------------------------------------

class TestSeverityLanguageBlind:
    """Severity must not differ based on language when is_emergency=False."""

    @pytest.mark.parametrize("lang", ["hi", "uz", "tg", "ky", "kk", "az", "ru", "en", "unknown"])
    def test_same_inputs_same_output_regardless_of_lang(
        self, env_vars: dict[str, str], lang: str
    ) -> None:
        from app.api.v1.chat_escalations import _severity  # noqa: PLC0415

        sev_ru, reason_ru = _severity("ru", is_answerable=False, confidence=None, escalate=False)
        sev, reason = _severity(lang, is_answerable=False, confidence=None, escalate=False)
        assert (sev, reason) == (sev_ru, reason_ru), (
            f"lang={lang!r} gave ({sev!r},{reason!r}) but 'ru' gave ({sev_ru!r},{reason_ru!r})"
        )
