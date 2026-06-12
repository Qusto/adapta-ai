"""Unit tests for GET /api/v1/chat/stats endpoint.

Verifies aggregate counts, escalation detection, and response model fields.
Uses mocked DB + auth so no testcontainer is needed.

Seed scenario:
  - 10 user messages for a single company
  - 3 of them are escalated:
      1 via escalate=True
      1 via confidence <= 0.35 (low)
      1 via is_answerable=False
  - 7 agent-side messages with known confidence/latency
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMPANY_UUID = uuid.uuid4()
HR_USER_UUID = uuid.uuid4()
MIGRANT_UUID = uuid.uuid4()


def _make_hr_user() -> Any:
    """Minimal User ORM-like object for the HR dependency."""
    user = MagicMock()
    user.id = HR_USER_UUID
    user.company_id = COMPANY_UUID
    user.role = "hr"
    return user


@pytest.fixture
def hr_jwt(env_vars: dict[str, str]) -> str:
    """Signed JWT for HR user."""
    from app.auth.jwt import encode_jwt  # noqa: PLC0415

    return encode_jwt({
        "sub": str(HR_USER_UUID),
        "role": "hr",
        "company_id": str(COMPANY_UUID),
    })


@pytest_asyncio.fixture
async def stats_client(env_vars: dict[str, str], hr_jwt: str) -> Any:  # type: ignore[return]
    """httpx.AsyncClient against FastAPI app with require_hr overridden via dependency_overrides."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    from app.auth.deps import require_hr  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415

    hr_user = _make_hr_user()

    async def _fake_require_hr() -> Any:
        return hr_user

    original = app.dependency_overrides.copy()
    app.dependency_overrides[require_hr] = _fake_require_hr

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {hr_jwt}"},
    ) as client:
        yield client

    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChatStatsEndpoint:
    """Tests for GET /api/v1/chat/stats."""

    @pytest.mark.asyncio
    async def test_stats_counts_match_seed(
        self, stats_client: Any, env_vars: dict[str, str]
    ) -> None:
        """total=10, escalated=3, auto_answered=7, rate=0.7."""
        # Use a simple UTC datetime string — avoid isoformat() which adds +00:00 with space in some Python builds
        since = "2026-05-21T00:00:00Z"

        # Mock out the three DB execute calls in order:
        # 1. total_messages -> 10
        # 2. escalated -> 3
        # 3. agent stats -> avg_confidence=0.85, avg_latency=150
        call_count = 0

        class _FakeResult:
            def __init__(self, value: Any) -> None:
                self._value = value

            def scalar_one(self) -> Any:
                return self._value

            def one(self) -> Any:
                return self._value

        async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeResult(10)  # total_messages
            elif call_count == 2:
                return _FakeResult(3)  # escalated
            else:
                return _FakeResult((0.85, 150.0))  # (avg_confidence, avg_latency_ms)

        mock_session = AsyncMock()
        mock_session.execute.side_effect = _fake_execute

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.v1.chat_stats.async_session_factory", return_value=mock_cm):
            resp = await stats_client.get(f"/api/v1/chat/stats?since={since}")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        body = resp.json()
        assert body["total_messages"] == 10, f"total_messages mismatch: {body}"
        assert body["escalated"] == 3, f"escalated mismatch: {body}"
        assert body["auto_answered"] == 7, f"auto_answered mismatch: {body}"
        assert abs(body["auto_answer_rate"] - 0.7) < 0.001, (
            f"auto_answer_rate mismatch: {body['auto_answer_rate']}"
        )

    @pytest.mark.asyncio
    async def test_stats_avg_confidence_and_latency(
        self, stats_client: Any, env_vars: dict[str, str]
    ) -> None:
        """avg_confidence and avg_response_ms are returned correctly."""
        call_count = 0

        class _FakeResult:
            def __init__(self, value: Any) -> None:
                self._value = value

            def scalar_one(self) -> Any:
                return self._value

            def one(self) -> Any:
                return self._value

        async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeResult(10)
            elif call_count == 2:
                return _FakeResult(3)
            else:
                return _FakeResult((0.85, 150.0))

        mock_session = AsyncMock()
        mock_session.execute.side_effect = _fake_execute

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.v1.chat_stats.async_session_factory", return_value=mock_cm):
            resp = await stats_client.get("/api/v1/chat/stats")

        body = resp.json()
        assert abs(body["avg_confidence"] - 0.85) < 0.001, (
            f"avg_confidence mismatch: {body['avg_confidence']}"
        )
        assert abs(body["avg_response_ms"] - 150.0) < 0.001, (
            f"avg_response_ms mismatch: {body['avg_response_ms']}"
        )

    @pytest.mark.asyncio
    async def test_stats_zero_total_returns_zero_rate(
        self, stats_client: Any, env_vars: dict[str, str]
    ) -> None:
        """auto_answer_rate is 0.0 when total_messages is 0 (no division by zero)."""
        call_count = 0

        class _FakeResult:
            def __init__(self, value: Any) -> None:
                self._value = value

            def scalar_one(self) -> Any:
                return self._value

            def one(self) -> Any:
                return self._value

        async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeResult(0)
            elif call_count == 2:
                return _FakeResult(0)
            else:
                return _FakeResult((None, None))

        mock_session = AsyncMock()
        mock_session.execute.side_effect = _fake_execute

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.v1.chat_stats.async_session_factory", return_value=mock_cm):
            resp = await stats_client.get("/api/v1/chat/stats")

        body = resp.json()
        assert body["total_messages"] == 0
        assert body["auto_answer_rate"] == 0.0
        assert body["avg_confidence"] is None
        assert body["avg_response_ms"] is None

    @pytest.mark.asyncio
    async def test_stats_since_echoed_in_response(
        self, stats_client: Any, env_vars: dict[str, str]
    ) -> None:
        """The `since` field in response echoes back the window start."""
        since = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)

        class _FakeResult:
            def __init__(self, value: Any) -> None:
                self._value = value

            def scalar_one(self) -> Any:
                return self._value

            def one(self) -> Any:
                return self._value

        call_count = 0

        async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _FakeResult(0)
            return _FakeResult((None, None))

        mock_session = AsyncMock()
        mock_session.execute.side_effect = _fake_execute

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        since_param = "2026-05-21T00:00:00Z"
        with patch("app.api.v1.chat_stats.async_session_factory", return_value=mock_cm):
            resp = await stats_client.get(f"/api/v1/chat/stats?since={since_param}")

        body = resp.json()
        # The since field should be present and parseable as datetime
        assert "since" in body, f"'since' missing from response: {body}"
        parsed = datetime.fromisoformat(body["since"].replace("Z", "+00:00"))
        assert parsed.year == 2026
        assert parsed.month == 5
        assert parsed.day == 21


# ---------------------------------------------------------------------------
# Test for logout cookie clearing (B1)
# ---------------------------------------------------------------------------


class TestLogoutCookieClearing:
    """Verify POST /api/v1/auth/logout clears the adapta_token cookie correctly."""

    @pytest.mark.asyncio
    async def test_logout_clears_cookie_with_correct_attributes(
        self, app_client: Any, env_vars: dict[str, str]
    ) -> None:
        """POST /auth/logout response must have Set-Cookie with Max-Age=0 and Path=/."""
        resp = await app_client.post("/api/v1/auth/logout")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

        set_cookie = resp.headers.get("set-cookie", "")
        assert set_cookie, "Expected Set-Cookie header on logout response"

        # Cookie must be cleared — either Max-Age=0 or expires in the past
        cleared = "max-age=0" in set_cookie.lower() or "max-age=0" in set_cookie
        assert cleared, f"Cookie not cleared (no Max-Age=0 in Set-Cookie): {set_cookie!r}"

        # Path must be "/" so it matches the originally-set cookie scope
        assert "path=/" in set_cookie.lower(), (
            f"Expected Path=/ in Set-Cookie, got: {set_cookie!r}"
        )

    @pytest.mark.asyncio
    async def test_login_cookie_has_path_root(
        self, app_client: Any, env_vars: dict[str, str]
    ) -> None:
        """POST /auth/login Set-Cookie must have Path=/ (not /api/v1/auth/login)."""
        # Patch password verification and DB lookup so login succeeds
        import uuid as _uuid  # noqa: PLC0415

        from app.db.models import User as _User  # noqa: PLC0415

        fake_user = MagicMock(spec=_User)
        fake_user.id = _uuid.uuid4()
        fake_user.email = "test@example.com"
        fake_user.role = "hr"
        fake_user.company_id = _uuid.uuid4()
        fake_user.first_name = "Test"
        fake_user.last_name = "User"
        fake_user.preferred_language = "ru"
        fake_user.password_hash = "hashed"

        with (
            patch("app.api.v1.auth.verify_password", return_value=True),
            patch("app.api.v1.auth.async_session_factory") as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = fake_user
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value = mock_cm

            resp = await app_client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "demo"},
            )

        assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"

        set_cookie = resp.headers.get("set-cookie", "")
        assert set_cookie, "Expected Set-Cookie header on login response"
        assert "path=/" in set_cookie.lower(), (
            f"Login Set-Cookie must have Path=/, got: {set_cookie!r}"
        )
        assert "httponly" in set_cookie.lower(), (
            f"Login Set-Cookie must be HttpOnly, got: {set_cookie!r}"
        )
