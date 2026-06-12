"""Phase 0 — `app.config.Settings` must load required env vars.

Expected to FAIL in red phase: `app.config` module does not exist yet.

Required fields (per ORCHESTRATION.md §6 and 00_infrastructure.md):
    - database_url
    - jwt_secret
    - invite_secret
    - gigachat_authorization_key
    - openrouter_api_key
"""

from __future__ import annotations

import pytest


REQUIRED_FIELDS: tuple[str, ...] = (
    "database_url",
    "jwt_secret",
    "invite_secret",
    "gigachat_authorization_key",
    "openrouter_api_key",
)


def test_settings_loads_required_env_vars(env_vars: dict[str, str]) -> None:
    """Settings() reads all required env vars and exposes them as attributes."""
    from app.config import Settings  # noqa: PLC0415 — red-phase import

    settings = Settings()

    for field in REQUIRED_FIELDS:
        assert hasattr(settings, field), (
            f"Settings is missing required field {field!r}"
        )
        value = getattr(settings, field)
        # SecretStr or plain string — both must resolve to a non-empty string.
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        assert value, f"Settings.{field} is empty"


def test_settings_raises_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge: instantiating Settings() with no env vars must raise ValidationError."""
    from pydantic import ValidationError  # noqa: PLC0415
    from app.config import Settings  # noqa: PLC0415

    # Wipe all the keys Settings may read.
    for key in (
        "DATABASE_URL",
        "JWT_SECRET",
        "INVITE_SECRET",
        "GIGACHAT_AUTHORIZATION_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
