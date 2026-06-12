"""Unit tests for app.rag.embedder — Phase 2 RAG (red phase).

Tests-first item #8: test_embedder_uses_passage_prefix_on_ingest_and_query_prefix_on_search.
Mocks SentenceTransformer.encode as a spy — verifies E5 prefix protocol.
These tests FAIL until implementation exists.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from app.rag.embedder import Embedder  # noqa: PLC0415


# Fake embedding vector (dim=768)
FAKE_VECTOR = [0.1] * 768


class TestEmbedder:
    def test_embed_passages_returns_list_of_vectors(self) -> None:
        """embed_passages returns a list of float vectors (one per chunk)."""
        texts = ["Смена начинается в 08:00.", "Обед с 12:00 до 13:00."]
        with patch(
            "sentence_transformers.SentenceTransformer.encode",
            return_value=[FAKE_VECTOR, FAKE_VECTOR],
        ):
            embedder = Embedder()
            result = embedder.embed_passages(texts)
        assert isinstance(result, list)
        assert len(result) == 2
        assert len(result[0]) == 768

    def test_embed_query_returns_single_vector(self) -> None:
        """embed_query returns a single float vector of dim 768."""
        with patch(
            "sentence_transformers.SentenceTransformer.encode",
            return_value=[FAKE_VECTOR],
        ):
            embedder = Embedder()
            result = embedder.embed_query("Во сколько начинается смена?")
        assert isinstance(result, list)
        assert len(result) == 768

    def test_embedder_uses_passage_prefix_on_ingest_and_query_prefix_on_search(
        self,
    ) -> None:
        """CRITICAL: E5 requires 'passage: ' prefix on ingest, 'query: ' on search.

        Spy on SentenceTransformer.encode and verify:
        - embed_passages() prepends 'passage: ' to each text
        - embed_query() prepends 'query: ' to the query text
        """
        encode_spy = MagicMock(return_value=[FAKE_VECTOR])

        with patch("sentence_transformers.SentenceTransformer.encode", encode_spy):
            embedder = Embedder()

            # Ingest path
            passage_texts = ["Рабочий день начинается в 08:00."]
            embedder.embed_passages(passage_texts)

            # Search path
            embedder.embed_query("Во сколько подъём?")

        # Collect all calls
        all_calls = encode_spy.call_args_list
        assert len(all_calls) >= 2, "Expected at least 2 encode() calls (passage + query)"

        # Find passage call — must have 'passage: ' prefix
        passage_call_found = False
        query_call_found = False
        for call_args in all_calls:
            args, kwargs = call_args
            # First positional arg is the input to encode()
            inputs = args[0] if args else kwargs.get("sentences", kwargs.get("input", []))
            if isinstance(inputs, list):
                for inp in inputs:
                    if inp.startswith("passage: "):
                        passage_call_found = True
                    if inp.startswith("query: "):
                        query_call_found = True
            elif isinstance(inputs, str):
                if inputs.startswith("passage: "):
                    passage_call_found = True
                if inputs.startswith("query: "):
                    query_call_found = True

        assert passage_call_found, (
            "embed_passages() must prepend 'passage: ' to each text for E5 model. "
            f"Actual calls: {all_calls}"
        )
        assert query_call_found, (
            "embed_query() must prepend 'query: ' to query text for E5 model. "
            f"Actual calls: {all_calls}"
        )

    def test_embed_passages_normalizes_yo_to_ye(self) -> None:
        """embed_passages normalizes ё→е for the embedding vector (stored text unchanged)."""
        encode_spy = MagicMock(return_value=[FAKE_VECTOR])

        with patch("sentence_transformers.SentenceTransformer.encode", encode_spy):
            embedder = Embedder()
            embedder.embed_passages(["Журавлёво 2"])

        all_calls = encode_spy.call_args_list
        prefixed_inputs = []
        for call_args in all_calls:
            args, kwargs = call_args
            inputs = args[0] if args else kwargs.get("sentences", kwargs.get("input", []))
            if isinstance(inputs, list):
                prefixed_inputs.extend(inputs)
            elif isinstance(inputs, str):
                prefixed_inputs.append(inputs)

        assert any("журавлево 2" in inp for inp in prefixed_inputs), (
            "embed_passages must normalize ё→е so 'Журавлёво 2' becomes 'журавлево 2' "
            f"in the encoded string. Actual inputs: {prefixed_inputs}"
        )

    def test_embed_query_normalizes_yo_to_ye(self) -> None:
        """embed_query normalizes ё→е for the embedding vector."""
        encode_spy = MagicMock(return_value=[FAKE_VECTOR])

        with patch("sentence_transformers.SentenceTransformer.encode", encode_spy):
            embedder = Embedder()
            embedder.embed_query("что такое журавлево")

        all_calls = encode_spy.call_args_list
        prefixed_inputs = []
        for call_args in all_calls:
            args, kwargs = call_args
            inputs = args[0] if args else kwargs.get("sentences", kwargs.get("input", []))
            if isinstance(inputs, list):
                prefixed_inputs.extend(inputs)
            elif isinstance(inputs, str):
                prefixed_inputs.append(inputs)

        assert any("журавлево" in inp for inp in prefixed_inputs), (
            f"embed_query must preserve normalized form. Actual inputs: {prefixed_inputs}"
        )

    def test_embedder_model_name_is_multilingual_e5_base(self) -> None:
        """Embedder must load intfloat/multilingual-e5-base model."""
        init_spy = MagicMock()
        with patch("sentence_transformers.SentenceTransformer.__init__", init_spy):
            init_spy.return_value = None
            Embedder()
        # The first positional arg (or model_name_or_path kwarg) must be the E5 model
        call_args = init_spy.call_args
        if call_args is not None:
            args, kwargs = call_args
            model_name = (
                args[0] if args else kwargs.get("model_name_or_path", kwargs.get("model", ""))
            )
            assert "multilingual-e5-base" in str(model_name), (
                f"Expected intfloat/multilingual-e5-base, got: {model_name}"
            )
