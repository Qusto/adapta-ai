"""Integration tests for Phase 3 chat input validation — RED phase.

Tests-first items covered:
  12. test_chat_validates_text_length
      - empty text -> 422
      - text > 1000 chars -> 422
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _make_migrant_jwt(user_id: str, company_id: str, env_vars: dict[str, str]) -> str:
    from app.auth.jwt import encode_jwt

    return encode_jwt({
        "sub": user_id,
        "role": "migrant",
        "company_id": company_id,
        "preferred_language": "ru",
    })


class TestChatValidation:
    """test_chat_validates_text_length — Tests-first item 12."""

    async def test_chat_validates_empty_text_returns_422(
        self,
        app_client: Any,
        db_session: Any,
        env_vars: dict[str, str],
    ) -> None:
        """POST /chat/messages with text='' must return 422 Unprocessable Entity."""
        from app.db.models import Company, User

        company = Company(name="Validation Company", inn=None)
        db_session.add(company)
        await db_session.flush()

        user = User(
            company_id=company.id,
            email=f"val_test_{uuid.uuid4()}@test.demo",
            password_hash=None,
            role="migrant",
            first_name="Val",
            last_name="Test",
            preferred_language="ru",
        )
        db_session.add(user)
        await db_session.flush()

        jwt_token = _make_migrant_jwt(str(user.id), str(company.id), env_vars)

        response = await app_client.post(
            "/api/v1/chat/messages",
            json={"text": "", "language": "ru"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        assert response.status_code == 422, (
            f"Expected 422 for empty text, got {response.status_code}: {response.text[:200]}"
        )

    async def test_chat_validates_text_too_long_returns_422(
        self,
        app_client: Any,
        db_session: Any,
        env_vars: dict[str, str],
    ) -> None:
        """POST /chat/messages with text > 1000 chars must return 422."""
        from app.db.models import Company, User

        company = Company(name="Validation Company 2", inn=None)
        db_session.add(company)
        await db_session.flush()

        user = User(
            company_id=company.id,
            email=f"val2_test_{uuid.uuid4()}@test.demo",
            password_hash=None,
            role="migrant",
            first_name="Val2",
            last_name="Test",
            preferred_language="ru",
        )
        db_session.add(user)
        await db_session.flush()

        jwt_token = _make_migrant_jwt(str(user.id), str(company.id), env_vars)

        too_long_text = "а" * 1001

        response = await app_client.post(
            "/api/v1/chat/messages",
            json={"text": too_long_text, "language": "ru"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        assert response.status_code == 422, (
            f"Expected 422 for text > 1000 chars, got {response.status_code}: "
            f"{response.text[:200]}"
        )

    async def test_chat_validates_exactly_1000_chars_is_accepted(
        self,
        app_client: Any,
        db_session: Any,
        env_vars: dict[str, str],
    ) -> None:
        """POST /chat/messages with text exactly 1000 chars must NOT return 422."""
        from app.db.models import Company, User

        company = Company(name="Validation Company 3", inn=None)
        db_session.add(company)
        await db_session.flush()

        user = User(
            company_id=company.id,
            email=f"val3_test_{uuid.uuid4()}@test.demo",
            password_hash=None,
            role="migrant",
            first_name="Val3",
            last_name="Test",
            preferred_language="ru",
        )
        db_session.add(user)
        await db_session.flush()

        jwt_token = _make_migrant_jwt(str(user.id), str(company.id), env_vars)

        from app.rag.retriever import RetrievedChunk

        fake_chunks = [
            RetrievedChunk(
                chunk_text="Тестовый чанк.",
                score=0.9,
                file_name="test.pdf",
                chunk_idx=1,
                page=1,
                company_id=str(company.id),
                language="ru",
                document_id=str(uuid.uuid4()),
            )
        ]
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = fake_chunks
        mock_gigachat = MagicMock()

        async def _fake_stream(*args, **kwargs):
            yield "Ответ."

        mock_gigachat.chat_stream = _fake_stream

        exact_text = "б" * 1000

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat

            response = await app_client.post(
                "/api/v1/chat/messages",
                json={"text": exact_text, "language": "ru"},
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        assert response.status_code != 422, (
            f"text of exactly 1000 chars should be accepted, got {response.status_code}"
        )
