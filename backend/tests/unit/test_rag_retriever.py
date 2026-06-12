"""Unit tests for app.rag.retriever — Phase 2 RAG (red phase).

Tests-first items:
  #6: test_retrieval_returns_top_5_with_scores
  #7: test_retrieval_filters_by_company_id
  #8: test_embedder_uses_passage_prefix_on_ingest_and_query_prefix_on_search (retriever side)

Mocks embedder + ChromaDB store for isolated unit tests.
These tests FAIL until implementation exists.
"""
from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.rag.retriever import Retriever, RetrievedChunk  # noqa: PLC0415

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"
FAKE_VECTOR = [0.1] * 768

# Fake ChromaDB query response (simulating 5 results)
FAKE_CHROMA_RESULTS: dict[str, Any] = {
    "ids": [["doc.pdf::0", "doc.pdf::1", "doc.pdf::2", "doc.pdf::3", "doc.pdf::4"]],
    "documents": [
        [
            "Смена начинается в 08:00.",
            "Обед с 12:00 до 13:00.",
            "Каска обязательна.",
            "Завтрак с 07:00.",
            "Ужин с 18:00.",
        ]
    ],
    "metadatas": [
        [
            {"file_name": "doc.pdf", "chunk_idx": 0, "page": 1, "company_id": "pik", "language": "ru"},
            {"file_name": "doc.pdf", "chunk_idx": 1, "page": 1, "company_id": "pik", "language": "ru"},
            {"file_name": "doc.pdf", "chunk_idx": 2, "page": 2, "company_id": "pik", "language": "ru"},
            {"file_name": "doc.pdf", "chunk_idx": 3, "page": 2, "company_id": "pik", "language": "ru"},
            {"file_name": "doc.pdf", "chunk_idx": 4, "page": 3, "company_id": "pik", "language": "ru"},
        ]
    ],
    "distances": [[0.05, 0.10, 0.15, 0.20, 0.25]],  # cosine distances
}


def _make_mock_store() -> MagicMock:
    """Create a mock VectorStore with a fake query() method."""
    mock_store = MagicMock()
    mock_store.query.return_value = [
        {
            "chunk_text": f"Chunk text {i}.",
            "score": round(1.0 - i * 0.05, 2),
            "file_name": "doc.pdf",
            "chunk_idx": i,
            "page": i + 1,
            "company_id": "pik",
        }
        for i in range(5)
    ]
    return mock_store


def _make_mock_embedder() -> MagicMock:
    """Create a mock Embedder with embed_query returning a fake vector."""
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = FAKE_VECTOR
    return mock_embedder


class TestRetriever:
    def test_retrieval_returns_top_5_with_scores(self) -> None:
        """CRITICAL: search() returns exactly 5 RetrievedChunk objects with scores desc.

        Tests-first item #6.
        """
        mock_store = _make_mock_store()
        mock_embedder = _make_mock_embedder()
        retriever = Retriever(store=mock_store, embedder=mock_embedder)

        results = retriever.search(query="во сколько подъём", company_id="pik")

        assert isinstance(results, list), "search() must return a list"
        assert len(results) == 5, f"Expected 5 results, got {len(results)}"

        for chunk in results:
            assert isinstance(chunk, RetrievedChunk), (
                f"Expected RetrievedChunk, got {type(chunk)}"
            )
            assert hasattr(chunk, "chunk_text")
            assert hasattr(chunk, "score")
            assert hasattr(chunk, "file_name")
            assert hasattr(chunk, "chunk_idx")

        # Scores must be descending
        scores = [c.score for c in results]
        assert scores == sorted(scores, reverse=True), (
            f"Scores must be in descending order: {scores}"
        )

    def test_retrieval_score_is_cosine_similarity_not_distance(self) -> None:
        """Score in RetrievedChunk is cosine similarity (1 - distance), range [0, 1]."""
        mock_store = _make_mock_store()
        mock_embedder = _make_mock_embedder()
        retriever = Retriever(store=mock_store, embedder=mock_embedder)

        results = retriever.search(query="тест", company_id="pik")
        for chunk in results:
            assert 0.0 <= chunk.score <= 1.0, (
                f"Score {chunk.score} out of [0, 1] range — must be cosine similarity"
            )

    def test_retrieval_filters_by_company_id(self) -> None:
        """CRITICAL: search() passes company_id to store.query().

        Tests-first item #7: only chunks for the requested company_id returned.
        """
        mock_store = MagicMock()
        mock_store.query.return_value = [
            {
                "chunk_text": "Смена в 08:00.",
                "score": 0.9,
                "file_name": "doc_a.pdf",
                "chunk_idx": 0,
                "page": 1,
                "company_id": "company_a",
            }
        ]
        mock_embedder = _make_mock_embedder()
        retriever = Retriever(store=mock_store, embedder=mock_embedder)

        retriever.search(query="во сколько смена?", company_id="company_a")

        # Verify store.query was called with the correct company_id filter
        mock_store.query.assert_called_once()
        call_kwargs = mock_store.query.call_args
        # Accept either positional or keyword args
        args, kwargs = call_kwargs
        company_id_passed = kwargs.get("company_id") or (args[1] if len(args) > 1 else None)
        assert company_id_passed == "company_a", (
            f"store.query() must be called with company_id='company_a', "
            f"got: {call_kwargs}"
        )

    def test_retrieval_calls_embed_query_with_query_prefix(self) -> None:
        """CRITICAL: Retriever calls embedder.embed_query (which applies 'query: ' prefix).

        Tests-first item #8 — retriever side of prefix verification.
        """
        mock_store = _make_mock_store()
        mock_embedder = _make_mock_embedder()
        retriever = Retriever(store=mock_store, embedder=mock_embedder)

        query_text = "во сколько подъём?"
        retriever.search(query=query_text, company_id="pik")

        # embed_query should have been called with the raw query text
        # (the 'query: ' prefix is applied inside embed_query itself)
        mock_embedder.embed_query.assert_called_once()
        call_args = mock_embedder.embed_query.call_args
        args, kwargs = call_args
        actual_query = args[0] if args else kwargs.get("text", kwargs.get("query", ""))
        assert actual_query == query_text, (
            f"embed_query() should receive the raw query text '{query_text}', "
            f"got '{actual_query}'. The 'query: ' prefix must be applied inside Embedder."
        )

    def test_retrieval_returns_empty_for_unknown_company(self) -> None:
        """search() returns empty list when store has no chunks for company."""
        mock_store = MagicMock()
        mock_store.query.return_value = []
        mock_embedder = _make_mock_embedder()
        retriever = Retriever(store=mock_store, embedder=mock_embedder)

        results = retriever.search(query="любой вопрос", company_id="nonexistent_company")
        assert results == [], f"Expected empty list, got {results}"

    def test_retrieval_chunk_has_document_id_field(self) -> None:
        """RetrievedChunk includes document_id for Phase 3 citations handoff."""
        mock_store = MagicMock()
        mock_store.query.return_value = [
            {
                "chunk_text": "Текст чанка.",
                "score": 0.88,
                "file_name": "doc.pdf",
                "chunk_idx": 0,
                "page": 1,
                "company_id": "pik",
                "document_id": "some-uuid-123",
            }
        ]
        mock_embedder = _make_mock_embedder()
        retriever = Retriever(store=mock_store, embedder=mock_embedder)

        results = retriever.search(query="вопрос", company_id="pik")
        assert len(results) >= 1
        chunk = results[0]
        assert hasattr(chunk, "document_id"), (
            "RetrievedChunk must have document_id field for Phase 3 citations. "
            "See phase card: 'Retriever returns list[{chunk_text, score, file_name, chunk_idx, document_id}]'"
        )
