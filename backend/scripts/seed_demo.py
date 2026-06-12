"""Seed demo data — Застройщик№1 + Дарья (HR).

Idempotent: re-running this script does not duplicate rows or fail.

Reads `DATABASE_URL` from the environment directly (does NOT depend on
`app.config.Settings`) so that the script remains usable even when
GigaChat/OpenRouter secrets are absent (e.g., in CI or unit-test environment).

Usage:
    python -m scripts.seed_demo              # idempotent insert
    python -m scripts.seed_demo --reset      # wipe demo data first, then seed

The `--reset` flag removes the test workers that e2e runs accumulate
(invites, ai_messages, documents, non-HR users) so a fresh demo starts from a
clean slate. The schema is left intact — only DATA is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger("scripts.seed_demo")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Fixed deterministic UUIDs so re-runs and tests can rely on stable identifiers.
PIK_COMPANY_ID: uuid.UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DARIA_USER_ID: uuid.UUID = uuid.UUID("22222222-2222-2222-2222-222222222222")
RAJU_INVITE_ID: uuid.UUID = uuid.UUID("33333333-3333-3333-3333-333333333333")

COMPANY_NAME: str = "Застройщик№1"
COMPANY_INN: str = "7700000001"

DARIA_EMAIL: str = "daria@pik.demo"
DARIA_PASSWORD: str = "demo"
DARIA_FIRST_NAME: str = "Дарья"
DARIA_LAST_NAME: str = "Соколова"

RAJU_INVITE_EMAIL: str = "raju.sharma@example.com"
RAJU_INVITE_FIRST_NAME: str = "Раджу"
RAJU_INVITE_LAST_NAME: str = "Шарма"
RAJU_INVITE_LANGUAGE: str = "hi"
RAJU_INVITE_TOKEN_HASH: str = "0000000000000000000000000000000000000000000000000000000000000001"


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set — required for scripts.seed_demo.")
    # Coerce sync URLs to asyncpg if the caller passed a psycopg-style URL.
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _seed_company(session: AsyncSession) -> None:
    existing = (
        await session.execute(
            text("SELECT id FROM companies WHERE name = :n"),
            {"n": COMPANY_NAME},
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info("company '%s' already present (id=%s) — skip", COMPANY_NAME, existing)
        return

    await session.execute(
        text("INSERT INTO companies (id, name, inn) VALUES (:id, :name, :inn)"),
        {"id": PIK_COMPANY_ID, "name": COMPANY_NAME, "inn": COMPANY_INN},
    )
    logger.info("inserted company '%s' (id=%s)", COMPANY_NAME, PIK_COMPANY_ID)


async def _seed_daria(session: AsyncSession) -> None:
    existing = (
        await session.execute(
            text("SELECT id FROM users WHERE email = :e"),
            {"e": DARIA_EMAIL},
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info("user '%s' already present (id=%s) — skip", DARIA_EMAIL, existing)
        return

    password_hash: str = bcrypt.hashpw(DARIA_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )

    await session.execute(
        text(
            "INSERT INTO users "
            "(id, company_id, email, password_hash, role, first_name, last_name, "
            " preferred_language) "
            "VALUES (:id, :company_id, :email, :password_hash, :role, :first_name, "
            "        :last_name, :preferred_language)"
        ),
        {
            "id": DARIA_USER_ID,
            "company_id": PIK_COMPANY_ID,
            "email": DARIA_EMAIL,
            "password_hash": password_hash,
            "role": "hr",
            "first_name": DARIA_FIRST_NAME,
            "last_name": DARIA_LAST_NAME,
            "preferred_language": "ru",
        },
    )
    logger.info("inserted HR user '%s' (id=%s)", DARIA_EMAIL, DARIA_USER_ID)


async def _seed_raju_invite(session: AsyncSession) -> None:
    existing = (
        await session.execute(
            text("SELECT id FROM invites WHERE token_hash = :h"),
            {"h": RAJU_INVITE_TOKEN_HASH},
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "invite for '%s' already present (id=%s) — skip",
            RAJU_INVITE_EMAIL,
            existing,
        )
        return

    expires_at = datetime.now(UTC) + timedelta(days=7)
    await session.execute(
        text(
            "INSERT INTO invites "
            "(id, company_id, email, first_name, last_name, preferred_language, "
            " token_hash, expires_at) "
            "VALUES (:id, :company_id, :email, :first_name, :last_name, "
            "        :preferred_language, :token_hash, :expires_at)"
        ),
        {
            "id": RAJU_INVITE_ID,
            "company_id": PIK_COMPANY_ID,
            "email": RAJU_INVITE_EMAIL,
            "first_name": RAJU_INVITE_FIRST_NAME,
            "last_name": RAJU_INVITE_LAST_NAME,
            "preferred_language": RAJU_INVITE_LANGUAGE,
            "token_hash": RAJU_INVITE_TOKEN_HASH,
            "expires_at": expires_at,
        },
    )
    logger.info("inserted invite for '%s' (id=%s)", RAJU_INVITE_EMAIL, RAJU_INVITE_ID)


async def _reset_demo_data(session: AsyncSession) -> None:
    """Wipe accumulated test data so demos start from a clean slate.

    Strategy: TRUNCATE the demo tables in FK-safe order with CASCADE. We
    keep the schema (no migrations rerun) and rebuild everything via the
    standard seed functions called after this.

    Tables touched (CASCADE picks up dependents):
        * ai_messages   — chat history from e2e runs
        * documents     — uploaded PDFs from RAG smoke tests
        * invites       — duplicate raju.sharma invites
        * users         — Дарья + accepted migrants
        * companies     — Застройщик№1 (re-created with deterministic id below)
    """
    logger.info("--reset: truncating demo data (schema is preserved)")
    await session.execute(
        text(
            "TRUNCATE TABLE ai_messages, documents, invites, users, companies "
            "RESTART IDENTITY CASCADE"
        )
    )
    logger.info("--reset: demo data wiped")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="seed_demo",
        description="Seed Застройщик№1 + Дарья + Раджу-invite for the AdaptaAI demo.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe demo tables (companies/users/invites/documents/ai_messages) "
        "before seeding. Schema is preserved.",
    )
    return parser.parse_args(argv)


async def main(args: argparse.Namespace | None = None) -> None:
    args = args or _parse_args([])
    db_url = _get_database_url()
    engine = create_async_engine(db_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            async with session.begin():
                if args.reset:
                    await _reset_demo_data(session)
                await _seed_company(session)
                await _seed_daria(session)
                await _seed_raju_invite(session)
        logger.info("seed_demo OK")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    cli_args = _parse_args(sys.argv[1:])
    asyncio.run(main(cli_args))
