"""Embedder — Phase 2 RAG ingestion §1.4.

Wraps `intfloat/multilingual-e5-base` (dim=768) with mandatory E5 prefixes:
- `"passage: "` for indexing (embed_passages)
- `"query: "` for search (embed_query)
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from sentence_transformers import SentenceTransformer

from app.rag.normalize import normalize_for_match

logger = logging.getLogger(__name__)

_MODEL_NAME = "intfloat/multilingual-e5-base"

# ---------------------------------------------------------------------------
# Patch sys.modules so that mock.patch("sentence_transformers.SentenceTransformer.encode")
# resolves correctly during unit tests.
# Python's import system may register sentence_transformers.SentenceTransformer
# as a stub module in sys.modules rather than the class itself, causing
# patch("sentence_transformers.SentenceTransformer.encode") to fail with
# AttributeError. We replace the sys.modules entry with the class so that
# the string-based patch resolves to SentenceTransformer.encode (the method).
# ---------------------------------------------------------------------------
_sys_key = "sentence_transformers.SentenceTransformer"
_current = sys.modules.get(_sys_key)
if _current is not None and not isinstance(_current, type):
    sys.modules[_sys_key] = SentenceTransformer  # type: ignore[assignment]


class Embedder:
    """Sentence-transformers embedder with E5 prefix protocol."""

    def __init__(self) -> None:
        self._model: Any = SentenceTransformer(_MODEL_NAME)
        logger.info("Embedder loaded model: %s", _MODEL_NAME)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of passage texts with 'passage: ' E5 prefix.

        Args:
            texts: Raw chunk texts (no prefix).

        Returns:
            List of float vectors, one per input text.
        """
        prefixed = [f"passage: {normalize_for_match(t)}" for t in texts]
        result = self._model.encode(prefixed, normalize_embeddings=True)
        # Support both numpy arrays (real model) and lists (test mocks)
        vectors: list[list[float]] = result.tolist() if hasattr(result, "tolist") else list(result)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text with 'query: ' E5 prefix.

        Args:
            text: Raw query string (no prefix).

        Returns:
            Float vector of dim 768.
        """
        prefixed = [f"query: {normalize_for_match(text)}"]
        result = self._model.encode(prefixed, normalize_embeddings=True)
        # Support both numpy arrays (real model) and lists (test mocks)
        vectors: list[list[float]] = result.tolist() if hasattr(result, "tolist") else list(result)
        return vectors[0]
