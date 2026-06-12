"""Unit tests for Phase 3 chat SSE streaming — RED phase.

Tests-first items covered:
  1. test_chat_endpoint_streams_sse_events
  9. test_chat_token_event_uses_text_field
  5. test_chat_escalate_flag_always_false_in_mvp (parametrized)
  7. test_chat_requires_migrant_jwt
  8. test_chat_handles_llm_error_gracefully

Mocks: GigaChatClient.chat_stream, QwenClient, Retriever.search.
No real LLM or DB calls are made.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

# Helper to parse raw SSE bytes into list of (event_name, data_dict)
_SSE_LINE_RE = re.compile(r"^(event|data): (.+)$")


def parse_sse_body(body: bytes) -> list[tuple[str, Any]]:
    """Parse SSE response body into list of (event_name, data) tuples."""
    events: list[tuple[str, Any]] = []
    current_event: str | None = None
    for raw_line in body.decode("utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("event:"):
            current_event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_str = line.removeprefix("data:").strip()
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = data_str
            if current_event is not None:
                events.append((current_event, data))
                current_event = None
    return events


class TestChatEndpointSseEvents:
    """test_chat_endpoint_streams_sse_events — Tests-first item 1."""

    async def test_chat_endpoint_streams_sse_events(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """POST /api/v1/chat/messages returns text/event-stream.

        Events must follow the order:
          message_started -> token (>=2) -> citations -> done
        Token events must use field 'text', not 'delta'.
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        # Patch Retriever.search and GigaChatClient.chat_stream in the chat module
        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat

            # Also patch get_current_user to return a fake migrant user
            fake_user = MagicMock()
            fake_user.id = uuid.UUID(env_vars.get("sub", str(uuid.uuid4())))
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

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:200]}"
        )
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Expected text/event-stream, got: {content_type}"
        )

        events = parse_sse_body(response.content)
        event_names = [name for name, _ in events]

        assert "message_started" in event_names, "SSE must contain message_started event"
        assert "done" in event_names, "SSE must contain done event"

        token_events = [(n, d) for n, d in events if n == "token"]
        assert len(token_events) >= 2, (
            f"Expected >= 2 token events, got {len(token_events)}"
        )

        # Verify ordering: message_started first, done last
        assert event_names[0] == "message_started", (
            f"First event must be message_started, got {event_names[0]!r}"
        )
        assert event_names[-1] == "done", (
            f"Last event must be done, got {event_names[-1]!r}"
        )


class TestChatTokenEventUsesTextField:
    """test_chat_token_event_uses_text_field — Tests-first item 9."""

    async def test_chat_token_event_uses_text_field(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Token events must use field 'text', NOT 'delta'.

        Per _OVERVIEW.md global invariant: 'text' (не 'delta') в SSE.
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
                        json={"text": "Тест поля text", "language": "ru"},
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        events = parse_sse_body(response.content)
        token_events = [(n, d) for n, d in events if n == "token"]

        assert len(token_events) > 0, "Must have at least one token event"

        for event_name, data in token_events:
            assert "text" in data, (
                f"token event data must have 'text' field, got keys: {list(data.keys())}"
            )
            assert "delta" not in data, (
                f"token event must NOT have 'delta' field — use 'text' per spec. "
                f"Got: {data}"
            )


class TestChatEscalateFlagAlwaysFalse:
    """test_chat_escalate_flag_always_false_in_mvp — Tests-first item 5."""

    @pytest.mark.parametrize("confidence_hint", [0.0, 0.42, 0.99])
    async def test_chat_escalate_flag_always_false_in_mvp(
        self,
        confidence_hint: float,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat: MagicMock,
    ) -> None:
        """done event must have escalate=false regardless of confidence value.

        Per PRD §6.7: escalate в MVP всегда false.
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
                        json={"text": "Тест эскалации", "language": "ru"},
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        events = parse_sse_body(response.content)
        done_events = [(n, d) for n, d in events if n == "done"]

        assert len(done_events) == 1, f"Expected 1 done event, got {len(done_events)}"
        _, done_data = done_events[0]

        assert "escalate" in done_data, "done event must have 'escalate' field"
        assert done_data["escalate"] is False, (
            f"escalate must be false in MVP, got: {done_data['escalate']!r}"
        )


class TestChatRequiresMigrantJwt:
    """test_chat_requires_migrant_jwt — Tests-first item 7."""

    async def test_chat_requires_migrant_jwt_missing_token_returns_401(
        self,
        env_vars: dict[str, str],
    ) -> None:
        """POST /chat/messages without Authorization header must return 401."""
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat/messages",
                json={"text": "Тест", "language": "ru"},
            )

        assert response.status_code == 401, (
            f"Expected 401 without JWT, got {response.status_code}"
        )

    async def test_chat_requires_migrant_jwt_hr_token_returns_403(
        self,
        env_vars: dict[str, str],
        hr_jwt: str,
    ) -> None:
        """POST /chat/messages with HR token must return 403 (role mismatch)."""
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat/messages",
                json={"text": "Тест", "language": "ru"},
                headers={"Authorization": f"Bearer {hr_jwt}"},
            )

        assert response.status_code == 403, (
            f"Expected 403 for HR JWT on migrant-only endpoint, got {response.status_code}"
        )


class TestChatHandlesLlmErrorGracefully:
    """test_chat_handles_llm_error_gracefully — Tests-first item 8."""

    async def test_chat_handles_llm_error_gracefully(
        self,
        env_vars: dict[str, str],
        migrant_jwt: str,
        mock_retriever: MagicMock,
        mock_gigachat_error: MagicMock,
    ) -> None:
        """When GigaChat raises asyncio.TimeoutError, response must contain:
        - event: error with code=LLM_TIMEOUT
        - event: done with confidence=0.0 and escalate=false
        Response must NOT crash (no 500 status).
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat_error

            fake_user = MagicMock()
            fake_user.role = "migrant"
            fake_user.company_id = uuid.uuid4()
            fake_user.preferred_language = "ru"

            with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={"text": "Тест таймаута", "language": "ru"},
                        headers={"Authorization": f"Bearer {migrant_jwt}"},
                    )

        # Response must be 200 (SSE stream opened) — error reported inside stream
        assert response.status_code == 200, (
            f"Expected 200 (SSE), got {response.status_code}: {response.text[:200]}"
        )

        events = parse_sse_body(response.content)
        event_names = [n for n, _ in events]

        assert "error" in event_names, (
            "SSE stream must contain an 'error' event on LLM timeout"
        )

        error_events = [(n, d) for n, d in events if n == "error"]
        _, error_data = error_events[0]
        assert error_data.get("code") == "LLM_TIMEOUT", (
            f"error event code must be LLM_TIMEOUT, got: {error_data.get('code')!r}"
        )

        done_events = [(n, d) for n, d in events if n == "done"]
        assert len(done_events) == 1, "SSE must contain done event even after error"
        _, done_data = done_events[0]
        assert done_data.get("confidence") == 0.0, (
            f"done.confidence must be 0.0 after LLM_TIMEOUT, got: {done_data.get('confidence')}"
        )
        assert done_data.get("escalate") is False, "done.escalate must be false"


class TestChatStreamingIsIncremental:
    """Proves tokens are delivered incrementally, not buffered-then-replayed.

    Uses an asyncio.Event handshake: the fake chat_stream pauses after
    yielding the first token and waits for the consumer to set the event.
    If the old buffering pattern is in place the producer never resumes
    (it waits inside the generator while the consumer is blocked waiting
    for the producer to finish), causing asyncio.wait_for to time out and
    the test to fail.
    """

    async def test_tokens_are_delivered_incrementally(
        self,
        env_vars: dict[str, str],
    ) -> None:
        """stream_chat_response must yield each token SSE event as it arrives."""
        from tests.unit.chat.conftest import FAKE_CHUNKS

        from app.chat.message_handler import stream_chat_response

        first_token_seen = asyncio.Event()

        async def _incremental_stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            yield "Смена "
            # Block until the consumer has already seen the first token event.
            # If the implementation buffers all tokens before yielding any SSE,
            # this wait is never reached and the consumer never sets the event,
            # so asyncio.wait_for below raises TimeoutError.
            await asyncio.wait_for(first_token_seen.wait(), timeout=2.0)
            yield "в 8:00."

        fake_gigachat = MagicMock()
        fake_gigachat.chat_stream = _incremental_stream

        fake_retriever = MagicMock()
        fake_retriever.search.return_value = FAKE_CHUNKS

        fake_qwen = MagicMock()

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
            patch("app.chat.message_handler.QwenClient") as MockQwen,
            patch("app.chat.message_handler.get_store", return_value=MagicMock()),
            patch("app.chat.message_handler.get_embedder", return_value=MagicMock()),
            patch("app.chat.message_handler._persist_messages", new=AsyncMock()),
        ):
            MockRetriever.return_value = fake_retriever
            MockGigaChat.return_value = fake_gigachat
            MockQwen.return_value = fake_qwen

            token_texts: list[str] = []
            gen = stream_chat_response(
                user_id=uuid.uuid4(),
                company_id=uuid.uuid4(),
                question="Во сколько начинается смена?",
                language="ru",
            )
            async for sse_str in gen:
                events = parse_sse_body(sse_str.encode("utf-8"))
                for event_name, data in events:
                    if event_name == "token" and isinstance(data, dict):
                        token_texts.append(data["text"])
                        if not first_token_seen.is_set():
                            # Signal producer after first token observed by consumer
                            first_token_seen.set()

        assert "Смена " in token_texts, (
            f"Expected 'Смена ' in token stream, got: {token_texts}"
        )
        assert "в 8:00." in token_texts, (
            f"Expected 'в 8:00.' in token stream, got: {token_texts}"
        )
        assert token_texts.index("Смена ") < token_texts.index("в 8:00."), (
            "Tokens must arrive in order"
        )
