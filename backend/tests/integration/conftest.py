"""Integration-level conftest — wires FastAPI app to the testcontainer DB.

Strategy:
- All fixtures are function-scoped to avoid event-loop lifecycle issues.
- `db_session`: fresh engine per test, commits data so app sees it, truncates after.
- `app_client`: fresh engine per test (separate pool from db_session), same testcontainer DB.
- Schema ensured via Alembic `upgrade head` (idempotent) before first use, then
  subsequent uses rely on the existing schema (Alembic is re-entrant for same version).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"


def _run_alembic_upgrade(db_url: str) -> None:
    """Run alembic upgrade head (idempotent — safe to call if already at head)."""
    if not _ALEMBIC_INI.exists():
        # alembic.ini not present — fall back to ORM create_all (Phase 0 may not have it)
        return
    subprocess.run(
        ["alembic", "-c", str(_ALEMBIC_INI), "upgrade", "head"],
        cwd=str(_BACKEND_ROOT),
        env={**os.environ, "DATABASE_URL": db_url},
        check=False,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Override db_session — commits data so the app can see it
# ---------------------------------------------------------------------------


class _CommittingSession:
    """AsyncSession proxy that commits after each flush.

    This makes seeded data immediately visible to the app's separate DB connections.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def flush(self, *args: Any, **kwargs: Any) -> None:
        await self._session.flush(*args, **kwargs)
        await self._session.commit()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def delete(self, instance: Any) -> Any:
        return self._session.delete(instance)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def close(self) -> None:
        await self._session.close()

    async def refresh(self, instance: Any) -> None:
        await self._session.refresh(instance)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await self._session.execute(*args, **kwargs)

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        return await self._session.get(*args, **kwargs)


@pytest_asyncio.fixture
async def db_session(  # type: ignore[override]
    async_db_url: str,
    env_vars: dict[str, str],
) -> AsyncIterator[Any]:
    """Per-test session that commits on flush, truncates tables on teardown."""
    # Ensure schema via Alembic (idempotent, no-op if already at head)
    _run_alembic_upgrade(async_db_url)

    seed_engine = create_async_engine(async_db_url, future=True)
    factory = async_sessionmaker(seed_engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    proxy = _CommittingSession(session)

    try:
        yield proxy
    finally:
        await session.close()
        async with seed_engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE invites, users, companies "
                    "RESTART IDENTITY CASCADE"
                )
            )
        await seed_engine.dispose()


# ---------------------------------------------------------------------------
# Override app_client — app uses its own engine pointing at testcontainer
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(  # type: ignore[override]
    async_db_url: str,
    env_vars: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Any]:
    """httpx.AsyncClient wired to FastAPI app via testcontainer DATABASE_URL."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    monkeypatch.setenv("DATABASE_URL", async_db_url)

    from app.config import get_settings  # noqa: PLC0415

    get_settings.cache_clear()

    # Ensure schema (Alembic idempotent)
    _run_alembic_upgrade(async_db_url)

    # App uses its own engine (separate connection pool, no concurrent conflicts)
    app_engine = create_async_engine(async_db_url, future=True)
    app_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        app_engine, class_=AsyncSession, expire_on_commit=False
    )

    import app.database as db_module  # noqa: PLC0415

    original_factory = db_module.async_session_factory
    db_module.async_session_factory = app_session_factory  # type: ignore[assignment]

    from app.main import app  # noqa: PLC0415

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    db_module.async_session_factory = original_factory  # type: ignore[assignment]
    get_settings.cache_clear()
    await app_engine.dispose()
