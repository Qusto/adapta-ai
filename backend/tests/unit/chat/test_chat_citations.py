"""Unit tests for Phase 3 chat citations — RED phase.

Tests-first items covered:
  2. test_chat_response_contains_at_least_one_citation
  10. test_chat_citations_reference_retrieved_chunks
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.unit.chat.conftest import DOCUMENT_ID, FAKE_CHUNKS
from tests.unit.chat.test_chat_streaming import parse_sse_body


pytestmark = pytest.mark.asyncio


class TestChatResponseContainsCitations:
    """test_chat_response_contains_at_least_one_citation — Tests-first item 2."""

    async def test_chat_response_contains_at_least_one_citation(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
    ) -> None:
        """citations event must be non-empty with required fields.

        Per PRD §6.7 citations schema:
          [{document_id, document_name, chunk_index, snippet, rank}]
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat

            fake_user = MagicMock()
            fake_user.role = "migrant"
            fake_user.company_id = uuid.uuid4()
            fake_user.preferred_language = "ru"

            with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={"text": "Во сколько начинается смена?", "language": "ru"},
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        events = parse_sse_body(response.content)
        citations_events = [(n, d) for n, d in events if n == "citations"]

        assert len(citations_events) >= 1, (
            "SSE stream must contain at least one 'citations' event"
        )

        _, citations_data = citations_events[0]
        citations_list = citations_data.get("citations", [])

        assert len(citations_list) >= 1, (
            f"citations list must be non-empty, got: {citations_list!r}"
        )

        first_citation = citations_list[0]
        required_fields = {"document_id", "document_name", "chunk_index", "snippet", "rank"}
        missing = required_fields - set(first_citation.keys())
        assert not missing, (
            f"Citation missing required fields: {missing}. Got: {list(first_citation.keys())}"
        )

        # Validate non-empty values for key fields
        assert first_citation["document_id"], "document_id must be non-empty"
        assert first_citation["document_name"], "document_name must be non-empty"
        assert isinstance(first_citation["chunk_index"], int), (
            f"chunk_index must be int, got {type(first_citation['chunk_index'])}"
        )
        assert first_citation["snippet"], "snippet must be non-empty"
        assert first_citation["rank"] == 1, (
            f"First citation rank must be 1, got {first_citation['rank']}"
        )


class TestChatCitationsReferenceRetrievedChunks:
    """test_chat_citations_reference_retrieved_chunks — Tests-first item 10."""

    async def test_chat_citations_reference_retrieved_chunks(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
    ) -> None:
        """Citations chunk_index values must match the retrieved chunks' chunk_idx.

        Verifies that the chat pipeline correctly maps RetrievedChunk.chunk_idx
        to citation.chunk_index in the SSE output.
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        # mock_retriever returns FAKE_CHUNKS with chunk_idx 7 and 12
        expected_chunk_indices = {chunk.chunk_idx for chunk in FAKE_CHUNKS}

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat

            fake_user = MagicMock()
            fake_user.role = "migrant"
            fake_user.company_id = uuid.uuid4()
            fake_user.preferred_language = "ru"

            with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={"text": "Расскажи о рабочем времени", "language": "ru"},
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        events = parse_sse_body(response.content)
        citations_events = [(n, d) for n, d in events if n == "citations"]

        assert citations_events, "Must have citations event"
        _, citations_data = citations_events[0]
        citations_list = citations_data.get("citations", [])

        assert citations_list, "Citations list must not be empty"

        returned_chunk_indices = {c["chunk_index"] for c in citations_list}
        overlap = expected_chunk_indices & returned_chunk_indices
        assert overlap, (
            f"Citation chunk_index values {returned_chunk_indices} must overlap with "
            f"retrieved chunks' chunk_idx {expected_chunk_indices}"
        )
