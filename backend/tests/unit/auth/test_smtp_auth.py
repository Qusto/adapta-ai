"""Unit tests for SMTP client real-auth path.

Verifies that when smtp_security / smtp_username / smtp_password are set,
the underlying aiosmtplib.send call receives the correct kwargs.

Default (MailHog) behaviour is covered by existing email tests — here we
exercise only the new real-SMTP branch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_send_invite_email_passes_tls_auth_when_configured(
    env_vars: dict,
) -> None:
    """With SMTP_SECURITY=tls + creds set, aiosmtplib.send must receive
    use_tls=True, start_tls=False, username=..., password=...."""
    from app.config import Settings, get_settings

    get_settings.cache_clear()

    from app.email import mailhog_client

    tls_settings = Settings(
        gigachat_authorization_key="dummy",
        openrouter_api_key="dummy",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        jwt_secret="x" * 32,
        invite_secret="x" * 32,
        smtp_host="smtp.yandex.ru",
        smtp_port=465,
        smtp_from="demo@yandex.ru",
        smtp_username="demo@yandex.ru",
        smtp_password="app-password-16ch",
        smtp_security="tls",
        _env_file=None,  # type: ignore[call-arg]
    )

    with (
        patch.object(mailhog_client, "get_settings", return_value=tls_settings),
        patch.object(
            mailhog_client.aiosmtplib, "send", new_callable=AsyncMock
        ) as mock_send,
    ):
        await mailhog_client.send_invite_email(
            to_email="recipient@example.com",
            first_name="Тест",
            last_name="Получатель",
            invite_url="http://localhost:8000/i/TOKEN",
            company_name="SMTP Smoke",
        )

    get_settings.cache_clear()

    assert mock_send.await_count == 1, "aiosmtplib.send must be called exactly once"
    _, kwargs = mock_send.call_args
    assert kwargs["hostname"] == "smtp.yandex.ru"
    assert kwargs["port"] == 465  # noqa: PLR2004
    assert kwargs["use_tls"] is True, "tls security must set use_tls=True"
    assert kwargs["start_tls"] is False, "tls (implicit) must NOT set start_tls"
    assert kwargs["username"] == "demo@yandex.ru"
    assert kwargs["password"] == "app-password-16ch"


@pytest.mark.asyncio
async def test_send_invite_email_default_mailhog_has_no_auth(
    monkeypatch: pytest.MonkeyPatch, env_vars: dict
) -> None:
    """Default (no SMTP_* overrides) must keep MailHog semantics:
    no use_tls, no start_tls, no auth kwargs.

    We force-clear any SMTP_* env vars that the developer may have in infra/.env
    so this test exercises the genuine default code path.
    """
    for var in (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_SECURITY",
        "SMTP_FROM",
    ):
        monkeypatch.delenv(var, raising=False)

    from app.config import Settings, get_settings

    get_settings.cache_clear()

    from app.email import mailhog_client

    # Build a Settings with explicit defaults — bypasses .env loading entirely.
    default_settings = Settings(
        gigachat_authorization_key="dummy",
        openrouter_api_key="dummy",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        jwt_secret="x" * 32,
        invite_secret="x" * 32,
        _env_file=None,  # type: ignore[call-arg]
    )

    with (
        patch.object(mailhog_client, "get_settings", return_value=default_settings),
        patch.object(
            mailhog_client.aiosmtplib, "send", new_callable=AsyncMock
        ) as mock_send,
    ):
        await mailhog_client.send_invite_email(
            to_email="dev@example.com",
            first_name="Dev",
            last_name="User",
            invite_url="http://localhost:8000/i/TOKEN",
            company_name="Dev Co",
        )

    get_settings.cache_clear()

    assert mock_send.await_count == 1
    _, kwargs = mock_send.call_args
    assert kwargs["use_tls"] is False, "default must NOT use implicit TLS"
    assert kwargs["start_tls"] is False, "default must NOT upgrade via STARTTLS"
    assert "username" not in kwargs, "MailHog default must not carry username"
    assert "password" not in kwargs, "MailHog default must not carry password"
