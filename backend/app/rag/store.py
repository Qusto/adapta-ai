"""ChromaDB vector store — Phase 2 RAG §1.5.

PersistentClient backed collection `employer_docs_demo` with cosine distance.
Chunk IDs follow format `{file_name}::{chunk_idx}`.

Also exposes `PARTNER_PRODUCTS_COLLECTION` and `get_partner_products_store()` for
the global partner-products collection shared across all tenants.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import chromadb

from app.config import get_settings
from app.rag.chunker import Chunk

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "employer_docs_demo"
PARTNER_PRODUCTS_COLLECTION = "partner_products"


class VectorStore:
    """Wraps a ChromaDB collection for upsert / query / delete operations."""

    def __init__(self, persist_dir: str | None = None) -> None:
        """Initialise ChromaDB client and get-or-create the collection.

        Args:
            persist_dir: Path to persist ChromaDB data. Uses CHROMA_PERSIST_PATH
                from settings if not provided.
        """
        if persist_dir is None:
            settings = get_settings()
            persist_dir = settings.chroma_persist_path

        self._client: Any = chromadb.PersistentClient(path=persist_dir)
        self.collection: Any = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,  # We embed ourselves
        )
        logger.info(
            "VectorStore initialised at %s — collection %s",
            persist_dir,
            _COLLECTION_NAME,
        )

    def upsert(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        company_id: str,
        language: str = "ru",
    ) -> None:
        """Add or update chunks in the collection.

        Chunk ID format: `{file_name}::{chunk_idx}`.
        Metadata stored per chunk: file_name, chunk_idx, page, language, company_id.

        Args:
            chunks: List of Chunk objects to store.
            embeddings: Corresponding embedding vectors (same length as chunks).
            company_id: Company identifier for multi-tenant filtering.
            language: Language code (default 'ru').
        """
        if not chunks:
            return

        ids = [f"{c.file_name}::{c.chunk_idx}" for c in chunks]
        documents = [c.text for c in chunks]
        metadatas: list[dict[str, Any]] = [
            {
                "file_name": c.file_name,
                "chunk_idx": c.chunk_idx,
                # ChromaDB requires non-None metadata values
                "page": c.page if c.page is not None else -1,
                "language": language,
                "company_id": company_id,
                "snippet": c.text[:200],
            }
            for c in chunks
        ]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(
            "Upserted %d chunks for file_name=%s company_id=%s",
            len(chunks),
            chunks[0].file_name if chunks else "?",
            company_id,
        )

    def delete_by_file_name(self, file_name: str) -> None:
        """Remove all chunks for a given file name.

        Args:
            file_name: The file name stored in chunk metadata.
        """
        self.collection.delete(where={"file_name": file_name})
        logger.info("Deleted all chunks for file_name=%s", file_name)

    def query(
        self,
        query_embedding: list[float],
        company_id: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for similar chunks filtered by company_id.

        Args:
            query_embedding: Query vector (dim=768).
            company_id: Filter to only return chunks for this company.
            n_results: Maximum number of results to return.

        Returns:
            List of dicts with keys: chunk_text, score, file_name, chunk_idx,
            page, company_id, and optionally document_id.
        """
        count = self.collection.count()
        if count == 0:
            return []
        actual_n = min(n_results, count)

        raw: dict[str, Any] = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=actual_n,
            where={"company_id": company_id},
            include=["documents", "metadatas", "distances"],
        )

        results: list[dict[str, Any]] = []
        ids_list: list[str] = raw.get("ids", [[]])[0]
        docs_list: list[str] = raw.get("documents", [[]])[0]
        metas_list: list[dict[str, Any]] = raw.get("metadatas", [[]])[0]
        dists_list: list[float] = raw.get("distances", [[]])[0]

        for i, (_chunk_id, doc, meta, dist) in enumerate(
            zip(ids_list, docs_list, metas_list, dists_list, strict=False)
        ):
            score = float(1.0 - dist)  # cosine similarity = 1 - cosine distance
            results.append(
                {
                    "chunk_text": doc,
                    "score": score,
                    "file_name": meta.get("file_name", ""),
                    "chunk_idx": meta.get("chunk_idx", i),
                    "page": meta.get("page"),
                    "company_id": meta.get("company_id", company_id),
                    "language": meta.get("language", "ru"),
                }
            )

        return results


class PartnerProductsStore:
    """VectorStore for the global `partner_products` collection (all tenants).

    Differs from VectorStore in that no company_id filter is applied on query —
    all chunks in the collection are visible to every migrant.
    """

    def __init__(self, persist_dir: str | None = None) -> None:
        if persist_dir is None:
            settings = get_settings()
            persist_dir = settings.chroma_persist_path

        self._client: Any = chromadb.PersistentClient(path=persist_dir)
        self.collection: Any = self._client.get_or_create_collection(
            name=PARTNER_PRODUCTS_COLLECTION,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )
        logger.info(
            "PartnerProductsStore initialised at %s — collection %s",
            persist_dir,
            PARTNER_PRODUCTS_COLLECTION,
        )

    def upsert(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        language: str = "ru",
    ) -> None:
        """Add or update chunks. No company_id filter — global collection."""
        if not chunks:
            return

        ids = [f"{c.file_name}::{c.chunk_idx}" for c in chunks]
        documents = [c.text for c in chunks]
        metadatas: list[dict[str, Any]] = [
            {
                "file_name": c.file_name,
                "chunk_idx": c.chunk_idx,
                "page": c.page if c.page is not None else -1,
                "language": language,
                "collection": PARTNER_PRODUCTS_COLLECTION,
                "snippet": c.text[:200],
            }
            for c in chunks
        ]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(
            "PartnerProductsStore: upserted %d chunks for file_name=%s",
            len(chunks),
            chunks[0].file_name if chunks else "?",
        )

    def delete_by_file_name(self, file_name: str) -> None:
        self.collection.delete(where={"file_name": file_name})
        logger.info("PartnerProductsStore: deleted chunks for file_name=%s", file_name)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 3,
    ) -> list[dict[str, Any]]:
        """Query without company_id filter — all chunks are global."""
        count = self.collection.count()
        if count == 0:
            return []
        actual_n = min(n_results, count)

        raw: dict[str, Any] = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=actual_n,
            include=["documents", "metadatas", "distances"],
        )

        results: list[dict[str, Any]] = []
        ids_list: list[str] = raw.get("ids", [[]])[0]
        docs_list: list[str] = raw.get("documents", [[]])[0]
        metas_list: list[dict[str, Any]] = raw.get("metadatas", [[]])[0]
        dists_list: list[float] = raw.get("distances", [[]])[0]

        for i, (_chunk_id, doc, meta, dist) in enumerate(
            zip(ids_list, docs_list, metas_list, dists_list, strict=False)
        ):
            score = float(1.0 - dist)
            results.append(
                {
                    "chunk_text": doc,
                    "score": score,
                    "file_name": meta.get("file_name", ""),
                    "chunk_idx": meta.get("chunk_idx", i),
                    "page": meta.get("page"),
                    "company_id": PARTNER_PRODUCTS_COLLECTION,
                    "language": meta.get("language", "ru"),
                    "collection": PARTNER_PRODUCTS_COLLECTION,
                    # Frontmatter-sourced fields (new)
                    "product_title": meta.get("product_title", meta.get("title", "")),
                    "product_subtitle": meta.get("product_subtitle", meta.get("subtitle", "")),
                    "product_url": meta.get("product_url", meta.get("url", "")),
                    "product_badge": meta.get("product_badge", meta.get("badge", "")),
                    # Legacy field names (backwards compat)
                    "title": meta.get("title", meta.get("product_title", "")),
                    "subtitle": meta.get("subtitle", meta.get("product_subtitle", "")),
                    "url": meta.get("url", meta.get("product_url", "")),
                    "badge": meta.get("badge", meta.get("product_badge", "")),
                }
            )

        return results


@lru_cache(maxsize=1)
def get_partner_products_store() -> PartnerProductsStore:
    """Process-wide PartnerProductsStore singleton."""
    return PartnerProductsStore()
