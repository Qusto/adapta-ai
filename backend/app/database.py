"""Async SQLAlchemy engine + session factory.

Exposes module-level `async_engine` and `async_session_factory` so that
- FastAPI dependencies can `async with async_session_factory() as session:`,
- Alembic env.py can use `async_engine` for migrations,
- tests can assert engine/factory existence (Phase 0 unit tests).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_settings = get_settings()

async_engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
