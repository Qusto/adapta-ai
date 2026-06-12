"""RAG singleton factory — Phase 2/3 integration fix.

Provides lru_cache-backed singletons for Embedder, VectorStore, and Retriever.
Rationale: Embedder() loads ~1 GB intfloat/multilingual-e5-base — must NOT be
instantiated per-request.  Use get_retriever() everywhere instead of
Retriever(store=None, embedder=None).
"""

from __future__ import annotations

from functools import lru_cache

from app.rag.embedder import Embedder
from app.rag.retriever import Retriever
from app.rag.store import VectorStore


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Return the process-wide Embedder singleton (loads e5-base once)."""
    return Embedder()


@lru_cache(maxsize=1)
def get_store() -> VectorStore:
    """Return the process-wide VectorStore singleton (persist_dir from config)."""
    return VectorStore()


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    """Return the process-wide Retriever singleton backed by real store+embedder."""
    return Retriever(store=get_store(), embedder=get_embedder())
