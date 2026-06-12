"""Retriever — Phase 2 RAG §2.

Orchestrates embed_query + store.query to return top-k chunks with scores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A single retrieved chunk with score and metadata."""

    chunk_text: str
    score: float
    file_name: str
    chunk_idx: int
    page: int | None = None
    company_id: str = ""
    language: str = "ru"
    document_id: str | None = None


class Retriever:
    """Orchestrates embedding + vector store for semantic search."""

    def __init__(self, store: Any, embedder: Any) -> None:
        """Initialise retriever with a VectorStore and Embedder.

        Args:
            store: VectorStore instance (or mock for tests).
            embedder: Embedder instance (or mock for tests).
        """
        self._store = store
        self._embedder = embedder

    def search(
        self,
        query: str,
        company_id: str,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Search for top-k relevant chunks for the given query.

        Steps:
        1. Embed query with 'query: ' prefix (via embedder.embed_query).
        2. Query the vector store filtered by company_id.
        3. Return results sorted by score descending.

        Args:
            query: Raw user query string.
            company_id: Company filter for multi-tenant isolation.
            top_k: Maximum number of results to return (default 5).

        Returns:
            List of RetrievedChunk objects sorted by score descending.
        """
        # Step 1: embed query (embedder applies 'query: ' prefix internally)
        query_embedding: list[float] = self._embedder.embed_query(query)

        # Step 2: query the store
        raw_results: list[dict[str, Any]] = self._store.query(
            query_embedding=query_embedding,
            company_id=company_id,
            n_results=top_k,
        )

        # Step 3: convert and sort by score descending
        chunks: list[RetrievedChunk] = []
        for item in raw_results:
            chunk = RetrievedChunk(
                chunk_text=item.get("chunk_text", ""),
                score=float(item.get("score", 0.0)),
                file_name=item.get("file_name", ""),
                chunk_idx=int(item.get("chunk_idx", 0)),
                page=item.get("page"),
                company_id=item.get("company_id", company_id),
                language=item.get("language", "ru"),
                document_id=item.get("document_id"),
            )
            chunks.append(chunk)

        chunks.sort(key=lambda c: c.score, reverse=True)
        logger.info(
            "Retriever search query=%r company_id=%s → %d chunks",
            query[:50],
            company_id,
            len(chunks),
        )
        return chunks
