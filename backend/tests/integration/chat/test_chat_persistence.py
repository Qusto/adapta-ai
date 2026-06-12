"""Integration tests for Phase 3 chat message persistence — RED phase.

Tests-first items covered:
  3. test_chat_persists_user_and_assistant_messages
     After stream: 2 ai_messages rows (role=user, role=agent) with correct user_id,
     language, and citations JSONB for agent row.

Uses testcontainers Postgres + Alembic migrations.
GigaChat and Retriever are mocked.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_migrant_jwt(user_id: str, company_id: str, env_vars: dict[str, str]) -> str:
    """Create a signed migrant JWT for the given user and company."""
    from app.auth.jwt import encode_jwt

    return encode_jwt({
        "sub": user_id,
        "role": "migrant",
        "company_id": company_id,
        "preferred_language": "ru",
    })


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


class TestChatPersistsMessages:
    """test_chat_persists_user_and_agent_messages — Tests-first item 3."""

    async def test_chat_persists_user_and_agent_messages(
        self,
        app_client: Any,
        db_session: Any,
        env_vars: dict[str, str],
    ) -> None:
        """After streaming response, Postgres must have 2 ai_messages rows.

        - role=user: contains the question text
        - role=agent: contains the answer text + citations JSONB + confidence
        Both rows must have the same user_id and language='ru'.
        """
        from app.db.models import Company, User

        # Seed company + migrant user
        company = Company(name="Test Company Persist", inn=None)
        db_session.add(company)
        await db_session.flush()

        user = User(
            company_id=company.id,
            email=f"persist_test_{uuid.uuid4()}@test.demo",
            password_hash=None,
            role="migrant",
            first_name="Raju",
            last_name="Sharma",
            preferred_language="ru",
        )
        db_session.add(user)
        await db_session.flush()

        user_id_str = str(user.id)
        company_id_str = str(company.id)
        jwt_token = _make_migrant_jwt(user_id_str, company_id_str, env_vars)

        from app.rag.retriever import RetrievedChunk

        doc_id = str(uuid.uuid4())
        fake_chunks = [
            RetrievedChunk(
                chunk_text="Смена начинается в 8:00.",
                score=0.91,
                file_name="DEMO_DOC_TBD_BY_SERGEY.pdf",
                chunk_idx=7,
                page=3,
                company_id=company_id_str,
                language="ru",
                document_id=doc_id,
            ),
        ]

        mock_retriever = MagicMock()
        mock_retriever.search.return_value = fake_chunks

        mock_gigachat = MagicMock()

        # SGR (Phase 3.5): GigaChat must return valid RagAnswer JSON for the
        # parser to succeed and citations to be populated.
        sgr_payload = (
            '{"is_answerable": true,'
            ' "reasoning": "В чанке [1] указано время начала смены — 8:00. '
            'Достаточно для ответа.",'
            ' "answer": "Смена начинается в 8:00 [1].",'
            ' "citations": [{'
            f' "document_id": "{doc_id}",'
            ' "document_title": "Демо документ ПИК",'
            ' "page_number": 3,'
            ' "snippet": "Смена начинается в 8:00. Стандартное рабочее время."'
            '}],'
            ' "confidence": "high"}'
        )

        async def _fake_stream(*args: Any, **kwargs: Any):
            # Yield in 3 chunks so legacy incremental-token tests still pass.
            n = max(2, len(sgr_payload) // 3)
            for i in range(0, len(sgr_payload), n):
                yield sgr_payload[i : i + n]

        mock_gigachat.chat_stream = _fake_stream

        with (
            patch("app.chat.message_handler.Retriever") as MockRetriever,
            patch("app.chat.message_handler.GigaChatClient") as MockGigaChat,
        ):
            MockRetriever.return_value = mock_retriever
            MockGigaChat.return_value = mock_gigachat

            response = await app_client.post(
                "/api/v1/chat/messages",
                json={"text": "Во сколько начинается смена?", "language": "ru"},
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:300]}"
        )

        # Query ai_messages for this user
        # AiMessage model must exist (will fail with ImportError in red phase)
        from app.db.models import AiMessage  # noqa: F401 — intentional ImportError in red

        result = await db_session.execute(
            select(AiMessage)
            .where(AiMessage.user_id == user.id)
            .order_by(AiMessage.created_at)
        )
        messages = result.scalars().all()

        assert len(messages) == 2, (
            f"Expected 2 ai_messages rows, got {len(messages)}"
        )

        user_msg = next((m for m in messages if m.role == "user"), None)
        agent_msg = next((m for m in messages if m.role == "agent"), None)

        assert user_msg is not None, "Must have a row with role='user'"
        assert agent_msg is not None, "Must have a row with role='agent'"

        assert user_msg.user_id == user.id, "user message user_id must match"
        assert agent_msg.user_id == user.id, "agent message user_id must match"

        assert user_msg.language == "ru", f"user message language must be 'ru', got {user_msg.language!r}"
        assert agent_msg.language == "ru", f"agent message language must be 'ru', got {agent_msg.language!r}"

        assert user_msg.text == "Во сколько начинается смена?", (
            f"user message text must match input, got {user_msg.text!r}"
        )

        # Agent message must have non-empty text
        assert agent_msg.text, "agent message text must be non-empty"

        # Citations JSONB for agent must be a list with at least one item
        assert agent_msg.citations is not None, "agent message citations must not be None"
        assert isinstance(agent_msg.citations, list), (
            f"agent citations must be list, got {type(agent_msg.citations)}"
        )
        assert len(agent_msg.citations) >= 1, (
            "agent citations list must have at least one item"
        )
