"""Unit tests for RagAnswer Pydantic schema — Phase 3.5 SGR."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.rag.schemas import Citation, RagAnswer


class TestCitationSchema:
    """Validation of the Citation submodel."""

    def test_citation_minimum_valid(self) -> None:
        cit = Citation(
            document_id="doc-1",
            document_title="Регламент общежития",
            page_number=3,
            snippet="A" * 20,
        )
        assert cit.document_id == "doc-1"
        assert cit.page_number == 3

    def test_citation_rejects_short_snippet(self) -> None:
        with pytest.raises(ValidationError):
            Citation(
                document_id="doc-1",
                document_title="Регламент",
                page_number=1,
                snippet="too short",  # < 20 chars
            )

    def test_citation_rejects_too_long_snippet(self) -> None:
        with pytest.raises(ValidationError):
            Citation(
                document_id="doc-1",
                document_title="Регламент",
                page_number=1,
                snippet="X" * 301,
            )

    def test_citation_requires_non_empty_title(self) -> None:
        with pytest.raises(ValidationError):
            Citation(
                document_id="doc-1",
                document_title="",
                page_number=1,
                snippet="X" * 50,
            )

    def test_citation_page_number_defaults_to_zero(self) -> None:
        cit = Citation(
            document_id="doc-1",
            document_title="DOCX без страниц",
            snippet="X" * 50,
        )
        assert cit.page_number == 0


class TestRagAnswerHappyPath:
    """RagAnswer accepts a well-formed SGR object."""

    def test_full_answerable_payload_validates(self) -> None:
        answer = RagAnswer(
            is_answerable=True,
            reasoning="В чанке [1] прямо указано время начала смены.",
            answer="Смена начинается в 8:00 [1].",
            citations=[
                Citation(
                    document_id="d1",
                    document_title="Регламент общежития ПИК",
                    page_number=3,
                    snippet="Смена начинается в 8:00. Завтрак до 7:30.",
                )
            ],
            confidence="high",
        )
        assert answer.is_answerable is True
        assert len(answer.citations) == 1
        assert answer.confidence == "high"

    def test_na_answer_with_empty_citations_validates(self) -> None:
        """`is_answerable=False` → answer='N/A' and citations=[]."""
        answer = RagAnswer(
            is_answerable=False,
            reasoning="В контексте нет фактов про зарплату — ответить честно не могу.",
            answer="N/A",
            citations=[],
            confidence="low",
        )
        assert answer.answer == "N/A"
        assert answer.citations == []


class TestRagAnswerEdgeCases:
    """Boundary and rejection cases."""

    def test_reasoning_minimum_length(self) -> None:
        with pytest.raises(ValidationError):
            RagAnswer(
                is_answerable=False,
                reasoning="too short",  # < 30 chars
                answer="N/A",
                citations=[],
                confidence="low",
            )

    def test_reasoning_maximum_length(self) -> None:
        with pytest.raises(ValidationError):
            RagAnswer(
                is_answerable=False,
                reasoning="X" * 401,  # > 400 chars
                answer="N/A",
                citations=[],
                confidence="low",
            )

    def test_confidence_must_be_one_of_literal(self) -> None:
        with pytest.raises(ValidationError):
            RagAnswer(
                is_answerable=True,
                reasoning="A" * 50,
                answer="Ответ",
                citations=[],
                confidence="very-high",  # not in Literal
            )

    @pytest.mark.parametrize("confidence", ["high", "medium", "low"])
    def test_confidence_accepts_all_literals(self, confidence: str) -> None:
        answer = RagAnswer(
            is_answerable=True,
            reasoning="A" * 50,
            answer="Ответ",
            citations=[],
            confidence=confidence,  # type: ignore[arg-type]
        )
        assert answer.confidence == confidence

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            RagAnswer(  # type: ignore[call-arg]
                is_answerable=True,
                reasoning="A" * 50,
                # answer missing
                citations=[],
                confidence="high",
            )

    def test_reasoning_exactly_30_chars_accepted(self) -> None:
        answer = RagAnswer(
            is_answerable=False,
            reasoning="X" * 30,
            answer="N/A",
            citations=[],
            confidence="low",
        )
        assert len(answer.reasoning) == 30
