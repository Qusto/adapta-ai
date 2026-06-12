"""Regression guard: Retriever DI in chat path (Phase 2↔Phase 3 integration).

Bug that was caught: message_handler.py hardcoded Retriever(store=None, embedder=None).
In docker, retriever.search() -> embedder.embed_query() -> AttributeError: 'NoneType'
object has no attribute 'embed_query'.

This test verifies:
1. get_retriever() returns a Retriever with non-None embedder and store.
2. stream_chat_response builds Retriever with real store/embedder (via get_store/get_embedder),
   not with None — confirmed by checking that patching the factory singletons propagates
   into the handler.
3. Regression: no RETRIEVAL_FAILED event when retriever is properly wired.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


class TestGetRetrieverSingleton:
    """Verify the factory returns properly wired singletons."""

    def test_get_retriever_embedder_is_not_none(self) -> None:
        """get_retriever()._embedder must NOT be None.

        This is the regression guard for the original bug:
            Retriever(store=None, embedder=None)
        which caused AttributeError: 'NoneType' has no attribute 'embed_query'
        in docker.
        """
        from unittest.mock import MagicMock, patch

        # Patch Embedder and VectorStore to avoid loading 1 GB model in tests
        mock_embedder = MagicMock()
        mock_store = MagicMock()

        with (
            patch("app.rag.factory.Embedder", return_value=mock_embedder),
            patch("app.rag.factory.VectorStore", return_value=mock_store),
        ):
            # Clear lru_cache so patch takes effect
            from app.rag import factory

            factory.get_embedder.cache_clear()
            factory.get_store.cache_clear()
            factory.get_retriever.cache_clear()

            retriever = factory.get_retriever()

        assert retriever._embedder is not None, (
            "get_retriever()._embedder must not be None — "
            "the original bug was Retriever(store=None, embedder=None)"
        )
        assert retriever._store is not None, (
            "get_retriever()._store must not be None"
        )

    def test_get_retriever_search_does_not_raise_attribute_error(self) -> None:
        """retriever.search() must not raise AttributeError even with lightweight mock.

        Regression: AttributeError: 'NoneType' object has no attribute 'embed_query'
        was the exact error message seen in docker logs.
        """
        from unittest.mock import MagicMock, patch

        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.0] * 768
        mock_store = MagicMock()
        mock_store.query.return_value = []

        with (
            patch("app.rag.factory.Embedder", return_value=mock_embedder),
            patch("app.rag.factory.VectorStore", return_value=mock_store),
        ):
            from app.rag import factory

            factory.get_embedder.cache_clear()
            factory.get_store.cache_clear()
            factory.get_retriever.cache_clear()

            retriever = factory.get_retriever()

        # Must not raise AttributeError
        try:
            results = retriever.search(query="тест", company_id="company-123")
        except AttributeError as exc:
            pytest.fail(
                f"retriever.search() raised AttributeError — embedder not wired: {exc}"
            )

        assert isinstance(results, list), "search() must return a list"


class TestMessageHandlerUsesFactorySingletons:
    """Verify message_handler builds Retriever with factory singletons, not None."""

    async def test_no_retrieval_failed_event_with_real_retriever_di(
        self,
        env_vars: dict[str, str],
    ) -> None:
        """When Retriever is wired via factory (not None), RETRIEVAL_FAILED must not appear.

        This is the critical regression check: before the fix, every chat request in docker
        emitted event: error RETRIEVAL_FAILED because embedder=None.
        """
        from httpx import ASGITransport, AsyncClient

        from app.auth.jwt import encode_jwt
        from app.main import app

        user_id = str(uuid.uuid4())
        company_id = str(uuid.uuid4())
        jwt_token = encode_jwt({
            "sub": user_id,
            "role": "migrant",
            "company_id": company_id,
            "preferred_language": "ru",
        })

        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1] * 768
        mock_store = MagicMock()
        mock_store.query.return_value = []

        # Patch factory singletons (lightweight, no 1GB model load)
        # Also patch GigaChat to avoid real network call
        mock_gigachat = MagicMock()

        async def _fake_stream(*args: Any, **kwargs: Any) -> Any:
            yield "Ответ тестовый."
            import asyncio as _asyncio
            await _asyncio.sleep(0)

        mock_gigachat.chat_stream = _fake_stream

        # Patch DB persistence to avoid needing a real Postgres connection
        import app.database as _db_module_ref

        with (
            patch("app.rag.factory.Embedder", return_value=mock_embedder),
            patch("app.rag.factory.VectorStore", return_value=mock_store),
            patch("app.chat.message_handler.GigaChatClient", return_value=mock_gigachat),
            patch.object(_db_module_ref, "async_session_factory"),
        ):
            from app.rag import factory

            factory.get_embedder.cache_clear()
            factory.get_store.cache_clear()
            factory.get_retriever.cache_clear()

            # Also need to patch the DB lookup for the user in require_migrant
            # Use dependency_overrides instead
            from app.api.v1.chat import require_migrant

            fake_user = MagicMock()
            fake_user.id = uuid.UUID(user_id)
            fake_user.role = "migrant"
            fake_user.company_id = uuid.UUID(company_id)
            fake_user.preferred_language = "ru"

            app.dependency_overrides[require_migrant] = lambda: fake_user

            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/chat/messages",
                        json={"text": "О чём этот документ?", "language": "ru"},
                        headers={"Authorization": f"Bearer {jwt_token}"},
                    )
            finally:
                app.dependency_overrides.pop(require_migrant, None)

        assert response.status_code == 200, (
            f"Chat endpoint must return 200, got {response.status_code}: "
            f"{response.text[:300]}"
        )

        body = response.text
        assert "RETRIEVAL_FAILED" not in body, (
            f"RETRIEVAL_FAILED event detected — embedder/store not wired correctly. "
            f"Response body: {body[:500]}"
        )
