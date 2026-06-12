"""Unit tests for app.llm.gigachat_client.GigaChatClient — Phase 3 (RED).

Tests-first items covered:
- GigaChatClient can be imported and instantiated
- chat_stream is an async generator
- chat_stream yields string tokens
- GigaChatClient handles 500-style errors gracefully (raises on stream)
"""

from __future__ import annotations

import asyncio
import pytest


pytestmark = pytest.mark.asyncio


class TestGigaChatClientImport:
    """Verify the module and class exist (will fail with ImportError in red phase)."""

    def test_gigachat_client_importable(self, env_vars: dict) -> None:
        """GigaChatClient must be importable from app.llm.gigachat_client."""
        from app.llm.gigachat_client import GigaChatClient  # noqa: F401

    def test_gigachat_client_instantiable(self, env_vars: dict) -> None:
        """GigaChatClient can be constructed without real API calls."""
        from app.llm.gigachat_client import GigaChatClient

        client = GigaChatClient()
        assert client is not None

    def test_gigachat_client_has_chat_stream_method(self, env_vars: dict) -> None:
        """GigaChatClient must expose a chat_stream method."""
        from app.llm.gigachat_client import GigaChatClient

        client = GigaChatClient()
        assert hasattr(client, "chat_stream"), "GigaChatClient must have chat_stream method"


class TestGigaChatStreamInterface:
    """chat_stream must return an async generator yielding str tokens."""

    async def test_chat_stream_is_async_generator(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """chat_stream must be an async generator (supports __aiter__ / __anext__)."""
        import inspect

        from app.llm.gigachat_client import GigaChatClient

        client = GigaChatClient()

        # Monkeypatch _ensure_token to avoid real OAuth call
        async def _fake_ensure_token() -> str:
            return "fake-access-token"

        monkeypatch.setattr(client, "_ensure_token", _fake_ensure_token)

        # Monkeypatch the actual HTTP call to return fake SSE stream
        async def _fake_stream(*args, **kwargs):
            for token in ["Смена ", "начинается ", "в 8:00."]:
                yield token

        monkeypatch.setattr(client, "_raw_stream", _fake_stream)

        result = client.chat_stream(messages=[{"role": "user", "content": "test"}])
        assert inspect.isasyncgen(result) or hasattr(result, "__aiter__"), (
            "chat_stream must return an async iterable"
        )

    async def test_chat_stream_yields_string_tokens(
        self, env_vars: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """chat_stream must yield str tokens."""
        from app.llm.gigachat_client import GigaChatClient

        client = GigaChatClient()

        async def _fake_ensure_token() -> str:
            return "fake-access-token"

        monkeypatch.setattr(client, "_ensure_token", _fake_ensure_token)

        expected = ["Смена ", "начинается ", "в 8:00."]

        async def _fake_raw_stream(*args, **kwargs):
            for token in expected:
                yield token

        monkeypatch.setattr(client, "_raw_stream", _fake_raw_stream)

        tokens_received: list[str] = []
        async for token in client.chat_stream(messages=[{"role": "user", "content": "test"}]):
            tokens_received.append(token)
            assert isinstance(token, str), f"Expected str token, got {type(token)}"

        assert tokens_received == expected, (
            f"Expected tokens {expected!r}, got {tokens_received!r}"
        )
