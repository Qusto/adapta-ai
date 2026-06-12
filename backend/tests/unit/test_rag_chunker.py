"""Unit tests for app.rag.chunker — Phase 2 RAG (red phase).

Tests-first: verifies chunking strategy (800 token / 100 overlap,
RecursiveCharacterTextSplitter) using a loaded document fixture.
These tests FAIL until implementation exists.
"""
from __future__ import annotations

import pathlib

import pytest

from app.rag.chunker import chunk_document, Chunk  # noqa: PLC0415
from app.rag.loader import load_pdf, load_docx  # noqa: PLC0415

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"

# A long text that should definitely produce more than 1 chunk (>800 tokens)
LONG_RUSSIAN_TEXT = (
    "Правила внутреннего распорядка. "
    "Рабочий день начинается в 08:00 и заканчивается в 17:00. "
    "Обеденный перерыв с 12:00 до 13:00. "
    "Использование мобильных телефонов во время работы запрещено. "
    "Сотрудник обязан соблюдать технику безопасности. "
    "Спецодежда и средства индивидуальной защиты обязательны на всех объектах. "
    "Каска должна быть надета в зоне строительства. "
    "Нарушение правил безопасности влечёт дисциплинарное взыскание. "
) * 30  # Repeat to exceed 800 tokens


class TestChunkDocument:
    def test_chunk_returns_list_of_chunk_objects(self) -> None:
        """chunk_document returns a non-empty list of Chunk objects."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        chunks = chunk_document(doc)
        assert isinstance(chunks, list)
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_chunk_has_required_fields(self) -> None:
        """Each Chunk has text, chunk_idx, page, file_name fields."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        chunks = chunk_document(doc)
        for chunk in chunks:
            assert hasattr(chunk, "text")
            assert hasattr(chunk, "chunk_idx")
            assert hasattr(chunk, "page")
            assert hasattr(chunk, "file_name")
            assert isinstance(chunk.text, str)
            assert len(chunk.text.strip()) > 0

    def test_chunk_idx_sequential(self) -> None:
        """chunk_idx values are sequential starting from 0."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        chunks = chunk_document(doc)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_idx == i

    def test_chunk_file_name_matches_document(self) -> None:
        """Each chunk's file_name matches the source document."""
        doc = load_pdf(FIXTURES / "demo_ru.pdf")
        chunks = chunk_document(doc)
        for chunk in chunks:
            assert chunk.file_name == "demo_ru.pdf"

    def test_long_text_produces_multiple_chunks(self) -> None:
        """Text longer than 800 tokens splits into multiple chunks."""
        from app.rag.loader import LoadedDocument, PageContent  # noqa: PLC0415
        # Build a synthetic doc with lots of text
        page = PageContent(text=LONG_RUSSIAN_TEXT, page_number=1)
        doc = LoadedDocument(file_name="synthetic.pdf", pages=[page])
        chunks = chunk_document(doc)
        assert len(chunks) > 1, (
            f"Expected multiple chunks for long text, got {len(chunks)}"
        )

    def test_chunk_size_does_not_vastly_exceed_800_tokens(self) -> None:
        """Chunks should be bounded — no chunk should be grossly over 800 tokens."""
        from app.rag.loader import LoadedDocument, PageContent  # noqa: PLC0415
        page = PageContent(text=LONG_RUSSIAN_TEXT, page_number=1)
        doc = LoadedDocument(file_name="synthetic.pdf", pages=[page])
        chunks = chunk_document(doc)
        # Allow up to 1.5x the target size as a sanity check
        for chunk in chunks:
            word_count = len(chunk.text.split())
            assert word_count <= 1200, (
                f"Chunk {chunk.chunk_idx} has {word_count} words — too large"
            )

    def test_docx_page_is_none(self) -> None:
        """Chunks from DOCX source have page=None."""
        doc = load_docx(FIXTURES / "Sample_Policy.docx")
        chunks = chunk_document(doc)
        for chunk in chunks:
            assert chunk.page is None
