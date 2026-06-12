"""Unit tests for SGR answer parser — Phase 3.5."""

from __future__ import annotations

import pytest

from app.rag.answer_parser import (
    SAFE_FALLBACK_ANSWER,
    ParseFailure,
    parse_rag_answer,
)
from app.rag.schemas import RagAnswer


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------


_VALID_JSON = (
    '{"is_answerable": true,'
    ' "reasoning": "В чанке [1] прямо указано время начала смены — 8:00.",'
    ' "answer": "Смена начинается в 8:00 [1].",'
    ' "citations": [{'
    ' "document_id": "d1",'
    ' "document_title": "Регламент общежития ПИК",'
    ' "page_number": 3,'
    ' "snippet": "Смена начинается в 8:00. Завтрак до 7:30."'
    '}],'
    ' "confidence": "high"}'
)

_VALID_NA_JSON = (
    '{"is_answerable": false,'
    ' "reasoning": "В контексте нет фактов про зарплату.",'
    ' "answer": "N/A",'
    ' "citations": [],'
    ' "confidence": "low"}'
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestParseHappyPath:

    def test_parse_bare_valid_json(self) -> None:
        result = parse_rag_answer(_VALID_JSON)
        assert isinstance(result, RagAnswer)
        assert result.is_answerable is True
        assert result.confidence == "high"
        assert len(result.citations) == 1

    def test_parse_na_case(self) -> None:
        result = parse_rag_answer(_VALID_NA_JSON)
        assert isinstance(result, RagAnswer)
        assert result.is_answerable is False
        assert result.answer == "N/A"
        assert result.citations == []

    def test_parse_with_markdown_fences(self) -> None:
        wrapped = f"```json\n{_VALID_JSON}\n```"
        result = parse_rag_answer(wrapped)
        assert isinstance(result, RagAnswer)
        assert result.is_answerable is True

    def test_parse_with_bare_fences(self) -> None:
        wrapped = f"```\n{_VALID_JSON}\n```"
        result = parse_rag_answer(wrapped)
        assert isinstance(result, RagAnswer)

    def test_parse_with_text_prefix(self) -> None:
        """GigaChat sometimes prefixes the JSON with a stray sentence."""
        prefixed = f"Конечно, вот ответ:\n{_VALID_JSON}"
        result = parse_rag_answer(prefixed)
        assert isinstance(result, RagAnswer)
        assert result.confidence == "high"

    def test_parse_with_text_suffix(self) -> None:
        suffixed = f"{_VALID_JSON}\nКонец ответа."
        result = parse_rag_answer(suffixed)
        assert isinstance(result, RagAnswer)


# ---------------------------------------------------------------------------
# Failure paths (always return ParseFailure, never raise)
# ---------------------------------------------------------------------------


class TestParseFailures:

    def test_empty_input(self) -> None:
        result = parse_rag_answer("")
        assert isinstance(result, ParseFailure)
        assert "empty" in result.error.lower()

    def test_whitespace_only_input(self) -> None:
        result = parse_rag_answer("   \n   ")
        assert isinstance(result, ParseFailure)

    def test_completely_invalid_json(self) -> None:
        result = parse_rag_answer("this is not json at all, no braces")
        assert isinstance(result, ParseFailure)

    def test_json_array_at_top(self) -> None:
        """A JSON array (not object) at top level is rejected."""
        result = parse_rag_answer('[1, 2, 3]')
        assert isinstance(result, ParseFailure)

    def test_partial_json_object(self) -> None:
        result = parse_rag_answer('{"is_answerable": true, "reasoning":')
        assert isinstance(result, ParseFailure)

    def test_schema_violation_missing_fields(self) -> None:
        result = parse_rag_answer('{"is_answerable": true}')
        assert isinstance(result, ParseFailure)
        assert "ValidationError" in result.error

    def test_schema_violation_bad_confidence(self) -> None:
        bad = _VALID_JSON.replace('"high"', '"superduper"')
        result = parse_rag_answer(bad)
        assert isinstance(result, ParseFailure)


# ---------------------------------------------------------------------------
# Robustness: N/A coercion
# ---------------------------------------------------------------------------


class TestNaCoercion:
    """If LLM says is_answerable=False but forgets to set answer='N/A',
    the parser coerces it instead of failing — pragmatic robustness."""

    def test_is_answerable_false_with_wrong_answer_is_coerced(self) -> None:
        wrong = (
            '{"is_answerable": false,'
            ' "reasoning": "Нет фактов в контексте — пишу пустой ответ.",'
            ' "answer": "Извините, не знаю.",'
            ' "citations": [],'
            ' "confidence": "low"}'
        )
        result = parse_rag_answer(wrong)
        assert isinstance(result, RagAnswer)
        assert result.answer == "N/A"
        assert result.citations == []

    def test_is_answerable_false_with_citations_clears_them(self) -> None:
        weird = (
            '{"is_answerable": false,'
            ' "reasoning": "Нет фактов, но почему-то добавил цитату.",'
            ' "answer": "N/A",'
            ' "citations": [{'
            ' "document_id": "d1", "document_title": "T",'
            ' "page_number": 1, "snippet": "' + "X" * 30 + '"'
            '}],'
            ' "confidence": "low"}'
        )
        result = parse_rag_answer(weird)
        assert isinstance(result, RagAnswer)
        assert result.citations == []


# ---------------------------------------------------------------------------
# Safe fallback constant invariants
# ---------------------------------------------------------------------------


class TestSafeFallback:

    def test_safe_fallback_is_valid_rag_answer(self) -> None:
        assert isinstance(SAFE_FALLBACK_ANSWER, RagAnswer)

    def test_safe_fallback_marks_unanswerable(self) -> None:
        assert SAFE_FALLBACK_ANSWER.is_answerable is False
        assert SAFE_FALLBACK_ANSWER.citations == []
        assert SAFE_FALLBACK_ANSWER.confidence == "low"

    def test_safe_fallback_answer_text_is_human_friendly(self) -> None:
        # NOT the literal "N/A" — we want the UI to show something readable.
        assert SAFE_FALLBACK_ANSWER.answer != "N/A"
        assert "попробуйте" in SAFE_FALLBACK_ANSWER.answer.lower()


# ---------------------------------------------------------------------------
# Reparser scenario: simulated double-failure path
# ---------------------------------------------------------------------------


class TestReparserFlow:
    """Documents the contract used by message_handler:

    1. First parse fails → handler issues reparse retry.
    2. Second parse also fails → handler falls back to SAFE_FALLBACK_ANSWER.

    This test only exercises the parser side of the contract — handler
    integration tests cover the full streaming path.
    """

    def test_double_parse_failure_path(self) -> None:
        first = parse_rag_answer("garbage prefix")
        second = parse_rag_answer("```not json```")
        assert isinstance(first, ParseFailure)
        assert isinstance(second, ParseFailure)
        # Handler MUST use SAFE_FALLBACK_ANSWER here:
        chosen = SAFE_FALLBACK_ANSWER
        assert chosen.is_answerable is False

    def test_first_fails_second_succeeds_path(self) -> None:
        first = parse_rag_answer("not json")
        second = parse_rag_answer(_VALID_JSON)
        assert isinstance(first, ParseFailure)
        assert isinstance(second, RagAnswer)
        # Handler MUST use `second`:
        assert second.is_answerable is True
