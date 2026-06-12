"""Phase 0 — `app.database` must expose an async session factory.

Expected to FAIL in red phase: `app.database` module does not exist yet.

The implementer is expected to create:
    backend/app/database.py
        async_engine = create_async_engine(settings.database_url, ...)
        async_session_factory = async_sessionmaker(async_engine, ...)
"""

from __future__ import annotations

from typing import Any

import pytest


def test_async_session_factory_is_callable(env_vars: dict[str, str]) -> None:
    """`app.database.async_session_factory` exists and is callable (a factory)."""
    from app import database  # noqa: PLC0415 — red-phase import

    assert hasattr(database, "async_session_factory"), (
        "app.database must expose `async_session_factory`"
    )
    factory: Any = database.async_session_factory
    assert callable(factory), (
        f"async_session_factory must be callable (a sessionmaker), got {type(factory).__name__}"
    )


def test_async_engine_is_exposed(env_vars: dict[str, str]) -> None:
    """Edge: module also exposes the underlying async engine (used by Alembic env.py)."""
    from sqlalchemy.ext.asyncio import AsyncEngine  # noqa: PLC0415

    from app import database  # noqa: PLC0415

    assert hasattr(database, "async_engine"), (
        "app.database must expose `async_engine`"
    )
    assert isinstance(database.async_engine, AsyncEngine), (
        f"async_engine must be SQLAlchemy AsyncEngine, got {type(database.async_engine).__name__}"
    )


@pytest.mark.asyncio
async def test_session_factory_yields_async_session(env_vars: dict[str, str]) -> None:
    """Edge: instantiating the factory returns an AsyncSession instance."""
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    from app import database  # noqa: PLC0415

    session = database.async_session_factory()
    try:
        assert isinstance(session, AsyncSession), (
            f"factory() must produce AsyncSession, got {type(session).__name__}"
        )
    finally:
        await session.close()
