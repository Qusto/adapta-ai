"""Unit tests for app.rag.store — Phase 2 RAG (red phase).

Tests-first item #4: test_chunks_stored_with_metadata.
Uses an isolated in-memory/tmp ChromaDB path via pytest tmp_path.
These tests FAIL until implementation exists.
"""
from __future__ import annotations

import pathlib
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.rag.store import VectorStore  # noqa: PLC0415
from app.rag.chunker import Chunk  # noqa: PLC0415
from app.rag.embedder import Embedder  # noqa: PLC0415

FAKE_VECTOR = [0.1] * 768


def make_chunks(
    file_name: str = "test_doc.pdf",
    company_id: str = "company_a",
    count: int = 3,
) -> list[Chunk]:
    """Build a list of Chunk objects for testing."""
    return [
        Chunk(
            text=f"Chunk text number {i} about working hours and safety.",
            chunk_idx=i,
            page=i + 1,
            file_name=file_name,
        )
        for i in range(count)
    ]


class TestVectorStore:
    def test_store_initializes_collection(self, tmp_path: pathlib.Path) -> None:
        """VectorStore creates collection 'employer_docs_demo' on init."""
        store = VectorStore(persist_dir=str(tmp_path))
        assert store.collection is not None
        assert store.collection.name == "employer_docs_demo"

    def test_chunks_stored_with_metadata(self, tmp_path: pathlib.Path) -> None:
        """CRITICAL: After upsert, each chunk in ChromaDB has required metadata fields.

        Metadata must include: file_name, chunk_idx, page, language, company_id.
        """
        store = VectorStore(persist_dir=str(tmp_path))
        chunks = make_chunks(file_name="demo_ru.pdf", company_id="pik_demo")
        embeddings = [FAKE_VECTOR for _ in chunks]

        store.upsert(
            chunks=chunks,
            embeddings=embeddings,
            company_id="pik_demo",
            language="ru",
        )

        # Query back the stored chunks
        result = store.collection.get(
            where={"file_name": "demo_ru.pdf"},
            include=["metadatas"],
        )
        assert result["ids"], "Expected chunks to be stored in ChromaDB"

        for meta in result["metadatas"]:
            assert "file_name" in meta, f"Missing 'file_name' in metadata: {meta}"
            assert "chunk_idx" in meta, f"Missing 'chunk_idx' in metadata: {meta}"
            assert "page" in meta, f"Missing 'page' in metadata: {meta}"
            assert "language" in meta, f"Missing 'language' in metadata: {meta}"
            assert "company_id" in meta, f"Missing 'company_id' in metadata: {meta}"
            assert meta["file_name"] == "demo_ru.pdf"
            assert meta["language"] == "ru"
            assert meta["company_id"] == "pik_demo"

    def test_upsert_idempotent_replaces_chunks(self, tmp_path: pathlib.Path) -> None:
        """Upserting same file_name twice replaces chunks (not appends).

        Tests-first item #2: test_pdf_reupload_replaces_old_chunks.
        After second upsert, only chunks from second batch exist.
        """
        store = VectorStore(persist_dir=str(tmp_path))
        file_name = "demo_ru.pdf"

        # First upload: 3 chunks
        first_chunks = make_chunks(file_name=file_name, count=3)
        first_embeddings = [FAKE_VECTOR for _ in first_chunks]
        store.upsert(first_chunks, first_embeddings, company_id="pik_demo", language="ru")

        count_after_first = store.collection.count()
        assert count_after_first == 3

        # Delete old chunks (idempotency delete step)
        store.delete_by_file_name(file_name)

        # Second upload: 5 chunks (different content count)
        second_chunks = make_chunks(file_name=file_name, count=5)
        second_embeddings = [FAKE_VECTOR for _ in second_chunks]
        store.upsert(second_chunks, second_embeddings, company_id="pik_demo", language="ru")

        count_after_second = store.collection.count()
        assert count_after_second == 5, (
            f"Expected 5 chunks after re-upload, got {count_after_second}. "
            "delete_by_file_name + upsert must replace, not append."
        )

    def test_delete_by_file_name_removes_chunks(self, tmp_path: pathlib.Path) -> None:
        """delete_by_file_name removes all chunks for the given file."""
        store = VectorStore(persist_dir=str(tmp_path))
        chunks = make_chunks(file_name="to_delete.pdf", count=4)
        embeddings = [FAKE_VECTOR for _ in chunks]
        store.upsert(chunks, embeddings, company_id="pik_demo", language="ru")

        assert store.collection.count() == 4

        store.delete_by_file_name("to_delete.pdf")
        assert store.collection.count() == 0

    def test_query_filters_by_company_id(self, tmp_path: pathlib.Path) -> None:
        """query() with company_id filter returns only chunks for that company.

        Tests-first item #7: test_retrieval_filters_by_company_id.
        """
        store = VectorStore(persist_dir=str(tmp_path))

        # Insert chunks for company A
        chunks_a = make_chunks(file_name="doc_a.pdf", company_id="company_a", count=3)
        embeddings_a = [FAKE_VECTOR for _ in chunks_a]
        store.upsert(chunks_a, embeddings_a, company_id="company_a", language="ru")

        # Insert chunks for company B
        chunks_b = make_chunks(file_name="doc_b.pdf", company_id="company_b", count=2)
        embeddings_b = [FAKE_VECTOR for _ in chunks_b]
        store.upsert(chunks_b, embeddings_b, company_id="company_b", language="ru")

        # Query for company A only
        result_a = store.query(
            query_embedding=FAKE_VECTOR,
            company_id="company_a",
            n_results=5,
        )
        for item in result_a:
            assert item["company_id"] == "company_a", (
                f"Expected only company_a chunks, got company_id={item['company_id']}"
            )

        # Query for company B only
        result_b = store.query(
            query_embedding=FAKE_VECTOR,
            company_id="company_b",
            n_results=5,
        )
        for item in result_b:
            assert item["company_id"] == "company_b"

    def test_chunk_id_format(self, tmp_path: pathlib.Path) -> None:
        """ChromaDB IDs follow format '{file_name}::{chunk_idx}'."""
        store = VectorStore(persist_dir=str(tmp_path))
        chunks = make_chunks(file_name="id_test.pdf", count=2)
        embeddings = [FAKE_VECTOR for _ in chunks]
        store.upsert(chunks, embeddings, company_id="test_co", language="ru")

        result = store.collection.get(where={"file_name": "id_test.pdf"})
        for chunk_id in result["ids"]:
            assert "::" in chunk_id, f"Chunk ID must be 'file_name::chunk_idx', got: {chunk_id}"
            parts = chunk_id.split("::")
            assert parts[0] == "id_test.pdf"
            assert parts[1].isdigit()

    def test_cyrillic_snippet_round_trip(self, tmp_path: pathlib.Path) -> None:
        """REGRESSION: snippet metadata must survive ChromaDB round-trip as valid Cyrillic.

        Guards against docker locale bug (LANG=C / ASCII encoding) that corrupted
        non-ASCII characters to '??????' in citations[].snippet.
        The snippet stored and retrieved from ChromaDB must equal the original Russian text,
        not an ASCII-encoded substitute.
        """
        store = VectorStore(persist_dir=str(tmp_path))

        cyrillic_text = (
            "Пересменка: временный перевод работника в другое подразделение. "
            "Оплата труда сохраняется согласно договору."
        )
        chunk = Chunk(
            text=cyrillic_text,
            chunk_idx=0,
            page=1,
            file_name="demo_ru.pdf",
        )

        store.upsert(
            chunks=[chunk],
            embeddings=[FAKE_VECTOR],
            company_id="pik_demo",
            language="ru",
        )

        result = store.collection.get(
            where={"file_name": "demo_ru.pdf"},
            include=["documents", "metadatas"],
        )

        assert result["ids"], "Expected at least one stored chunk"

        # Verify the document (chunk_text) is preserved as valid Cyrillic
        stored_doc: str = result["documents"][0]
        assert stored_doc == cyrillic_text, (
            f"Document text corrupted. Expected Cyrillic, got: {stored_doc!r}"
        )
        assert "?" not in stored_doc, (
            f"Document contains '?' — likely ASCII encoding corruption: {stored_doc!r}"
        )

        # Verify the snippet metadata field is preserved as valid Cyrillic
        stored_snippet: str = result["metadatas"][0]["snippet"]
        expected_snippet = cyrillic_text[:200]
        assert stored_snippet == expected_snippet, (
            f"Snippet corrupted after round-trip. Expected: {expected_snippet!r}, "
            f"Got: {stored_snippet!r}"
        )
        assert "?" not in stored_snippet, (
            f"Snippet contains '?' — docker locale (LANG=C) ASCII encoding bug: "
            f"{stored_snippet!r}. Fix: add ENV LANG=C.UTF-8 PYTHONIOENCODING=utf-8 "
            f"to backend/Dockerfile."
        )
