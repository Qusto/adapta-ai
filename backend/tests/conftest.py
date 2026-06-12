"""Shared pytest fixtures for AdaptaAI backend tests.

Phase 0 (Infrastructure) — RED phase scaffolding. These fixtures intentionally
import modules that do not yet exist (`app.main`, `app.config`, `app.database`).
That makes every consuming test fail at collection / setup time, which is the
correct TDD "red" state. The Phase 0 implementer will create the modules and
flip the tests to green.

Fixture inventory:
    - env_vars           : monkeypatches the minimum env vars Settings() needs.
    - pg_container       : testcontainers-postgres 16 (session-scoped, slow).
    - sync_db_url        : sync psycopg URL for Alembic / DDL introspection.
    - async_db_url       : asyncpg URL for SQLAlchemy AsyncEngine.
    - db_engine          : SQLAlchemy AsyncEngine bound to pg_container.
    - db_session         : AsyncSession per test, rollback after.
    - app_client         : httpx.AsyncClient wired to FastAPI app via ASGITransport.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Marker registration  (implementer should also declare these in pyproject)
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so warnings don't pollute the red-phase output."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration (require testcontainers/Postgres)",
    )


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Session-scoped event loop so async fixtures (pg_container, engine) survive."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

REQUIRED_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "JWT_SECRET": "test-jwt-secret-32-bytes-long-xxxxxxxxxxxxxx",
    "JWT_ALGORITHM": "HS256",
    "INVITE_SECRET": "test-invite-secret-32-bytes-long-xxxxxxxxxx",
    "GIGACHAT_AUTHORIZATION_KEY": "dummy-base64-authorization-key",
    "GIGACHAT_SCOPE": "GIGACHAT_API_PERS",
    "GIGACHAT_MODEL": "GigaChat-2-Pro",
    "GIGACHAT_BASE_URL": "https://gigachat.devices.sberbank.ru/api/v1",
    "GIGACHAT_OAUTH_URL": "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
    "OPENROUTER_API_KEY": "sk-or-v1-dummy",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "QWEN_MODEL": "qwen/qwen-2.5-72b-instruct",
}


@pytest.fixture
def env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Inject the minimum env vars Settings() needs to instantiate."""
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    return dict(REQUIRED_ENV)


# ---------------------------------------------------------------------------
# Postgres testcontainer  (integration tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container() -> Iterator[Any]:
    """Postgres 16 container, shared across the session."""
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def sync_db_url(pg_container: Any) -> str:
    """psycopg2 sync URL — for Alembic and inspect()."""
    return pg_container.get_connection_url()


@pytest.fixture(scope="session")
def async_db_url(pg_container: Any) -> str:
    """asyncpg URL — for SQLAlchemy AsyncEngine."""
    sync_url: str = pg_container.get_connection_url()
    # testcontainers returns e.g. postgresql+psycopg2://... — rewrite to asyncpg
    return sync_url.replace("postgresql+psycopg2", "postgresql+asyncpg").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


@pytest_asyncio.fixture
async def db_engine(async_db_url: str) -> AsyncIterator[Any]:
    """Async SQLAlchemy engine bound to the test container."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(async_db_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: Any) -> AsyncIterator[Any]:
    """Per-test AsyncSession with rollback."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with db_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app_client(env_vars: dict[str, str]) -> AsyncIterator[Any]:
    """httpx.AsyncClient against the FastAPI app via ASGITransport.

    Fails (ImportError) until `app.main` exists. That's the red signal.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app  # noqa: PLC0415 — intentional import-time failure in red phase

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
