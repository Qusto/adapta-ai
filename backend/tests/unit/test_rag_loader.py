"""Unit tests for app.rag.loader — Phase 2 RAG (red phase).

Tests-first: verifies that loader.py extracts text from PDF and DOCX fixtures.
These tests FAIL (ImportError / ModuleNotFoundError) until implementation exists.
"""
from __future__ import annotations

import pathlib

import pytest

# Intentional import that will fail until implementation exists — TDD red phase.
from app.rag.loader import load_pdf, load_docx, LoadedDocument  # noqa: PLC0415

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# PDF loader
# ---------------------------------------------------------------------------

class TestLoadPdf:
    def test_pdf_returns_loaded_document(self) -> None:
        """load_pdf returns a LoadedDocument with non-empty pages list."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        assert isinstance(doc, LoadedDocument)
        assert len(doc.pages) >= 1

    def test_pdf_pages_have_text(self) -> None:
        """Each page in LoadedDocument has non-empty text."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        for page in doc.pages:
            assert isinstance(page.text, str)
            assert len(page.text.strip()) > 0

    def test_pdf_pages_have_page_numbers(self) -> None:
        """Each page carries a 1-based page number."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        for i, page in enumerate(doc.pages):
            assert page.page_number == i + 1

    def test_pdf_file_name_preserved(self) -> None:
        """LoadedDocument.file_name equals the input file's name."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        assert doc.file_name == "demo_ru.pdf"

    def test_pdf_nonexistent_raises(self) -> None:
        """load_pdf raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_pdf(pathlib.Path("/nonexistent/path/file.pdf"))


# ---------------------------------------------------------------------------
# DOCX loader
# ---------------------------------------------------------------------------

class TestLoadDocx:
    def test_docx_returns_loaded_document(self) -> None:
        """load_docx returns a LoadedDocument."""
        doc = load_docx(FIXTURES / "Sample_Policy.docx")
        assert isinstance(doc, LoadedDocument)

    def test_docx_has_paragraphs(self) -> None:
        """load_docx returns at least one page with non-empty text."""
        doc = load_docx(FIXTURES / "Sample_Policy.docx")
        assert len(doc.pages) >= 1
        full_text = " ".join(p.text for p in doc.pages)
        assert len(full_text.strip()) > 0

    def test_docx_page_number_is_none(self) -> None:
        """DOCX has no page numbers; page.page_number must be None."""
        doc = load_docx(FIXTURES / "Sample_Policy.docx")
        for page in doc.pages:
            assert page.page_number is None

    def test_docx_file_name_preserved(self) -> None:
        """LoadedDocument.file_name equals the input file's name."""
        doc = load_docx(FIXTURES / "Sample_Policy.docx")
        assert doc.file_name == "Sample_Policy.docx"
