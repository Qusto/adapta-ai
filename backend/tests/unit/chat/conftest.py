"""Fixtures for Phase 3 chat unit tests.

Provides mock_gigachat, mock_qwen, mock_retriever, and migrant_jwt fixtures.
All external LLM calls are mocked — no real network access.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.rag.retriever import RetrievedChunk


# ---------------------------------------------------------------------------
# Canonical test data
# ---------------------------------------------------------------------------

COMPANY_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())
DOCUMENT_ID = str(uuid.uuid4())

FAKE_CHUNKS: list[RetrievedChunk] = [
    RetrievedChunk(
        chunk_text="Смена начинается в 8:00. Завтрак до 7:30.",
        score=0.91,
        file_name="DEMO_DOC_TBD_BY_SERGEY.pdf",
        chunk_idx=7,
        page=3,
        company_id=COMPANY_ID,
        language="ru",
        document_id=DOCUMENT_ID,
    ),
    RetrievedChunk(
        chunk_text="Обед с 12:00 до 13:00 в столовой.",
        score=0.85,
        file_name="DEMO_DOC_TBD_BY_SERGEY.pdf",
        chunk_idx=12,
        page=5,
        company_id=COMPANY_ID,
        language="ru",
        document_id=DOCUMENT_ID,
    ),
]

# SGR (Phase 3.5): GigaChat now must return a JSON object matching RagAnswer.
# We split a real JSON payload into a few chunks so streaming tests still see
# >= 2 token events, but the buffered concatenation parses cleanly.
_FAKE_RAG_ANSWER_JSON = (
    '{"is_answerable": true,'
    ' "reasoning": "В чанке [1] прямо указано время начала смены — 8:00. '
    'Достаточно для ответа.",'
    ' "answer": "Смена начинается в 8:00 [1]. Завтрак с 7:00 до 7:30 [1].",'
    ' "citations": ['
    '{"document_id": "%s",'
    ' "document_title": "Регламент общежития ПИК",'
    ' "page_number": 3,'
    ' "snippet": "Смена начинается в 8:00. Завтрак до 7:30."}'
    '],'
    ' "confidence": "high"}'
)


def _fake_tokens_for(document_id: str) -> list[str]:
    """Split the JSON answer into ~4 streaming chunks."""
    payload = _FAKE_RAG_ANSWER_JSON % document_id
    # Roughly quarter-split so we always emit >= 2 token events
    n = max(2, len(payload) // 4)
    return [payload[i : i + n] for i in range(0, len(payload), n)]


# Hindi answer text — Qwen Step B is mocked to return this.
FAKE_HINDI_ANSWER = "पाली 8:00 बजे शुरू होती है [1]."

# Legacy alias kept for any tests that import it directly. The mock_gigachat
# fixture below builds tokens based on DOCUMENT_ID at call time, so this
# constant is mostly a backwards-compatible placeholder.
FAKE_GIGACHAT_TOKENS = _fake_tokens_for(DOCUMENT_ID)


# ---------------------------------------------------------------------------
# Migrant JWT token fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def migrant_jwt_payload() -> dict[str, Any]:
    """Minimal JWT payload for a migrant user."""
    return {
        "sub": USER_ID,
        "role": "migrant",
        "company_id": COMPANY_ID,
        "preferred_language": "ru",
    }


@pytest.fixture
def migrant_jwt(env_vars: dict[str, str], migrant_jwt_payload: dict[str, Any]) -> str:
    """Signed JWT token for a migrant user."""
    from app.auth.jwt import encode_jwt

    return encode_jwt(migrant_jwt_payload)


@pytest.fixture
def hr_jwt(env_vars: dict[str, str]) -> str:
    """Signed JWT token for an HR user (should be rejected by chat endpoint)."""
    from app.auth.jwt import encode_jwt

    return encode_jwt({
        "sub": str(uuid.uuid4()),
        "role": "hr",
        "company_id": COMPANY_ID,
    })


# ---------------------------------------------------------------------------
# Mock Retriever
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_retriever() -> MagicMock:
    """MagicMock for app.rag.retriever.Retriever with fixed search results."""
    mock = MagicMock()
    mock.search.return_value = FAKE_CHUNKS
    return mock


# ---------------------------------------------------------------------------
# Mock GigaChat client
# ---------------------------------------------------------------------------


async def _fake_chat_stream(
    tokens: list[str] | None = None,
) -> AsyncIterator[str]:
    """Async generator that yields fake tokens one by one."""
    for token in (tokens or FAKE_GIGACHAT_TOKENS):
        yield token
        await asyncio.sleep(0)


@pytest.fixture
def mock_gigachat() -> MagicMock:
    """MagicMock for app.llm.gigachat_client.GigaChatClient.chat_stream.

    Returns an async generator yielding chunks of a valid `RagAnswer` JSON
    so the SGR parser succeeds. Multiple chunks → tests that count token
    events still see >= 2 events.
    """
    mock = MagicMock()
    tokens = _fake_tokens_for(DOCUMENT_ID)

    async def _stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        for token in tokens:
            yield token
            await asyncio.sleep(0)

    mock.chat_stream = _stream
    return mock


@pytest.fixture
def mock_gigachat_error() -> MagicMock:
    """GigaChatClient mock that raises asyncio.TimeoutError on chat_stream call."""
    mock = MagicMock()

    async def _stream_error(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        raise asyncio.TimeoutError("GigaChat timeout")
        yield  # make it an async generator  # noqa: unreachable

    mock.chat_stream = _stream_error
    return mock


# ---------------------------------------------------------------------------
# Mock Qwen client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_qwen() -> MagicMock:
    """MagicMock for app.llm.qwen_client.QwenClient with fixed translate results."""
    mock = MagicMock()
    mock.translate_hi_to_ru = AsyncMock(
        return_value={"ru_query": "Во сколько начинается моя смена?", "intent": "schedule"}
    )
    mock.translate_ru_to_hi = AsyncMock(return_value=FAKE_HINDI_ANSWER)
    # canonicalize_ru: используется для ru-пути вместо translate_*
    mock.canonicalize_ru = AsyncMock(
        return_value={"ru_query": "Во сколько начинается смена?"}
    )
    return mock


@pytest.fixture
def mock_qwen_step_b_error() -> MagicMock:
    """QwenClient mock where translate_ru_to_hi raises an exception (5xx fallback)."""
    mock = MagicMock()
    mock.translate_hi_to_ru = AsyncMock(
        return_value={"ru_query": "Во сколько начинается моя смена?", "intent": "schedule"}
    )
    mock.translate_ru_to_hi = AsyncMock(
        side_effect=Exception("Qwen 500 Internal Server Error")
    )
    mock.canonicalize_ru = AsyncMock(
        return_value={"ru_query": "Во сколько начинается смена?"}
    )
    return mock
