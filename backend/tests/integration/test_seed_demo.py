"""Phase 0 — `python -m scripts.seed_demo` must create ГК ПИК + Дарья.

Expected to FAIL in red phase: `backend/scripts/seed_demo.py` does not exist.

Per phase card §Tests-first item 4 and 07_DATA_MODEL_AND_API.md §2.1-2.2:
    - companies: name = "ГК ПИК"
    - users: email = "daria@pik.demo", role = "hr"
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_seed_demo_creates_pik_and_daria(sync_db_url: str) -> None:
    """Run seed script against migrated DB; verify company + HR row exist."""
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    alembic_ini = BACKEND_ROOT / "alembic.ini"
    seed_script = BACKEND_ROOT / "scripts" / "seed_demo.py"
    assert seed_script.exists(), (
        f"scripts/seed_demo.py not found at {seed_script} — implementer must create it"
    )

    async_url = sync_db_url.replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    ).replace("postgresql://", "postgresql+asyncpg://")
    env = {**os.environ, "DATABASE_URL": async_url}

    # 1) Migrate first.
    migrate = subprocess.run(
        ["alembic", "-c", str(alembic_ini), "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrate.returncode == 0, (
        f"alembic upgrade head failed before seed:\n{migrate.stderr}"
    )

    # 2) Run seed script.
    seed = subprocess.run(
        ["python", "-m", "scripts.seed_demo"],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert seed.returncode == 0, (
        f"scripts.seed_demo failed:\nSTDOUT:{seed.stdout}\nSTDERR:{seed.stderr}"
    )

    # 3) Inspect DB.
    engine = create_engine(sync_db_url, future=True)
    try:
        with engine.connect() as conn:
            company_count = conn.execute(
                text("SELECT COUNT(*) FROM companies WHERE name = :n"),
                {"n": "ГК ПИК"},
            ).scalar_one()
            assert company_count == 1, (
                f"expected exactly 1 company named 'ГК ПИК', got {company_count}"
            )

            daria_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM users "
                    "WHERE email = :e AND role = :r"
                ),
                {"e": "daria@pik.demo", "r": "hr"},
            ).scalar_one()
            assert daria_count == 1, (
                f"expected exactly 1 HR user daria@pik.demo, got {daria_count}"
            )

            password_hash = conn.execute(
                text("SELECT password_hash FROM users WHERE email = :e"),
                {"e": "daria@pik.demo"},
            ).scalar_one()
            assert password_hash, "Дарья must have non-empty bcrypt password_hash"
            assert password_hash.startswith(("$2b$", "$2a$", "$2y$")), (
                f"expected bcrypt hash for daria, got prefix {password_hash[:4]!r}"
            )
    finally:
        engine.dispose()


@pytest.mark.integration
def test_seed_demo_is_idempotent(sync_db_url: str) -> None:
    """Edge: running seed twice must not raise and must not duplicate rows."""
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    alembic_ini = BACKEND_ROOT / "alembic.ini"
    async_url = sync_db_url.replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    ).replace("postgresql://", "postgresql+asyncpg://")
    env = {**os.environ, "DATABASE_URL": async_url}

    subprocess.run(
        ["alembic", "-c", str(alembic_ini), "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env=env,
        check=True,
        capture_output=True,
    )
    for _ in range(2):
        result = subprocess.run(
            ["python", "-m", "scripts.seed_demo"],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"seed_demo re-run failed:\n{result.stderr}"
        )

    engine = create_engine(sync_db_url, future=True)
    try:
        with engine.connect() as conn:
            n_companies = conn.execute(
                text("SELECT COUNT(*) FROM companies WHERE name = :n"),
                {"n": "ГК ПИК"},
            ).scalar_one()
            n_daria = conn.execute(
                text("SELECT COUNT(*) FROM users WHERE email = :e"),
                {"e": "daria@pik.demo"},
            ).scalar_one()
    finally:
        engine.dispose()

    assert n_companies == 1, f"company duplicated: {n_companies}"
    assert n_daria == 1, f"daria duplicated: {n_daria}"
