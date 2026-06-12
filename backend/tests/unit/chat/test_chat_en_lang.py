"""WS-E — English pivot-RU path: en→ru (Step A), RAG in ru, ru→en (Step B).

Emulates the chat with language="en" and mocked Qwen/GigaChat to verify the
answer comes back in English (not Russian) and Qwen is called both ways.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.chat.test_chat_streaming import parse_sse_body

pytestmark = pytest.mark.asyncio

_FAKE_EN_ANSWER = "Your shift starts at 8:00 [1]."


@pytest.fixture
def mock_qwen_en() -> MagicMock:
    mock = MagicMock()
    mock.translate_en_to_ru = AsyncMock(
        return_value={"ru_query": "Во сколько начинается смена?", "intent": "schedule"}
    )
    mock.translate_ru_to_en = AsyncMock(return_value=_FAKE_EN_ANSWER)
    # hi methods present but unused
    mock.translate_hi_to_ru = AsyncMock(return_value={"ru_query": "x", "intent": "other"})
    mock.translate_ru_to_hi = AsyncMock(return_value="x")
    return mock


async def test_chat_english_pivot_ru(
    env_vars: dict[str, str],
    migrant_jwt: str,
    mock_retriever: MagicMock,
    mock_gigachat: MagicMock,
    mock_qwen_en: MagicMock,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    with (
        patch("app.chat.message_handler.Retriever") as MockRetriever,
        patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
        patch("app.chat.message_handler.QwenClient") as MockQwen,
    ):
        MockRetriever.return_value = mock_retriever
        MockGigaChat.return_value = mock_gigachat
        MockQwen.return_value = mock_qwen_en

        fake_user = MagicMock()
        fake_user.role = "migrant"
        fake_user.company_id = uuid.uuid4()
        fake_user.preferred_language = "en"

        with patch("app.api.v1.chat.require_migrant", return_value=fake_user):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/chat/messages",
                    json={"text": "When does my shift start?", "language": "en"},
                    headers={"Authorization": f"Bearer {migrant_jwt}"},
                )

    assert response.status_code == 200, response.text
    # Both directions of Qwen translation were used for the English path
    mock_qwen_en.translate_en_to_ru.assert_called_once()
    mock_qwen_en.translate_ru_to_en.assert_called_once()
    # The English answer is present in the stream
    body = response.content.decode()
    assert _FAKE_EN_ANSWER in body, "English-translated answer must be streamed"
