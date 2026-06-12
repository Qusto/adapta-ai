"""Phase 0 — Alembic migrations must create the three core tables.

Expected to FAIL in red phase: no `alembic.ini`, no `migrations/env.py`,
no `migrations/versions/0001_*.py`.

Uses a fresh testcontainers-postgres 16 instance per test, runs
`alembic upgrade head`, then introspects the schema via SQLAlchemy `inspect`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES: frozenset[str] = frozenset({"companies", "users", "invites"})


@pytest.mark.integration
def test_alembic_creates_companies_users_invites(sync_db_url: str) -> None:
    """`alembic upgrade head` against an empty Postgres creates 3 core tables."""
    from sqlalchemy import create_engine, inspect  # noqa: PLC0415

    alembic_ini = BACKEND_ROOT / "alembic.ini"
    assert alembic_ini.exists(), (
        f"alembic.ini not found at {alembic_ini} — implementer must create it"
    )

    env = {
        "DATABASE_URL": sync_db_url.replace(
            "postgresql+psycopg2", "postgresql+asyncpg"
        ).replace("postgresql://", "postgresql+asyncpg://"),
    }
    result = subprocess.run(
        ["alembic", "-c", str(alembic_ini), "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env={**env, "PATH": __import__("os").environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nSTDOUT:{result.stdout}\nSTDERR:{result.stderr}"
    )

    engine = create_engine(sync_db_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    missing = EXPECTED_TABLES - tables
    assert not missing, (
        f"After alembic upgrade head expected tables {sorted(EXPECTED_TABLES)}, "
        f"missing: {sorted(missing)}. Found: {sorted(tables)}"
    )


@pytest.mark.integration
def test_alembic_downgrade_base_drops_tables(sync_db_url: str) -> None:
    """Edge: downgrade to base must remove the three tables (clean reversal)."""
    from sqlalchemy import create_engine, inspect  # noqa: PLC0415

    alembic_ini = BACKEND_ROOT / "alembic.ini"
    assert alembic_ini.exists(), "alembic.ini missing"

    env = {
        "DATABASE_URL": sync_db_url.replace(
            "postgresql+psycopg2", "postgresql+asyncpg"
        ).replace("postgresql://", "postgresql+asyncpg://"),
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    subprocess.run(
        ["alembic", "-c", str(alembic_ini), "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["alembic", "-c", str(alembic_ini), "downgrade", "base"],
        cwd=str(BACKEND_ROOT),
        env=env,
        check=True,
        capture_output=True,
    )

    engine = create_engine(sync_db_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    leftover = EXPECTED_TABLES & tables
    assert not leftover, (
        f"After downgrade base expected core tables removed, still present: {sorted(leftover)}"
    )
