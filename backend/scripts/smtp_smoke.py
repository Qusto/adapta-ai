"""SMTP smoke test — send a single invite email via the configured SMTP provider.

Used to verify Yandex / Gmail / any real SMTP credentials before recording demo.
Reads connection params from app.config.get_settings() — same path as production.

Usage:
    python -m scripts.smtp_smoke your-real-email@example.com
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.config import get_settings
from app.email.mailhog_client import send_invite_email

logger = logging.getLogger("scripts.smtp_smoke")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def _run(to_email: str) -> None:
    settings = get_settings()

    auth_marker = settings.smtp_username or "<no-auth>"
    print(
        f"SMTP smoke: sending to {to_email} "
        f"via {settings.smtp_host}:{settings.smtp_port} "
        f"(security={settings.smtp_security}, auth={auth_marker}, "
        f"from={settings.smtp_from})"
    )

    invite_url = f"{settings.invite_base_url}/SMOKE_TOKEN"

    await send_invite_email(
        to_email=to_email,
        first_name="Тестовый",
        last_name="Получатель",
        invite_url=invite_url,
        company_name="SMTP Smoke Test",
    )

    print(f"OK: send_invite_email returned without raising; check inbox of {to_email}.")


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("Usage: python -m scripts.smtp_smoke <recipient-email>", file=sys.stderr)
        sys.exit(2)

    asyncio.run(_run(sys.argv[1].strip()))


if __name__ == "__main__":
    main()
