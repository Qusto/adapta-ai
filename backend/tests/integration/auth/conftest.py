"""Phase 1 integration fixtures — Auth + Invite + HR notifications.

Fixtures:
    seed_hr              : ensures daria@pik.demo + ГК ПИК exist in DB.
    hr_token             : valid JWT with role=hr, company_id=pik_company_id.
    valid_invite         : an Invite row + its raw HMAC token for raju@example.com.
    client_authed_as_hr  : httpx.AsyncClient with HR Bearer header set.
    tampered_jwt         : string — valid JWT with payload segment flipped.
    db_session_with_users: db_session that already has two users (one new, one old).
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# seed_hr — ensure daria@pik.demo and ГК ПИК exist in the test DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def seed_hr(db_session, env_vars):  # noqa: ANN001
    """Insert ГК ПИК company + Дарья HR user into the test database.

    Relies on app.db.models and passlib bcrypt — will fail ImportError until
    Phase 1 implementer creates the modules.
    """
    from app.db.models import Company, User  # type: ignore[import]
    from app.auth.password import hash_password  # type: ignore[import]

    company = Company(
        id=uuid.uuid4(),
        name="ГК ПИК",
        inn="7713011336",
    )
    db_session.add(company)
    await db_session.flush()

    hr_user = User(
        id=uuid.uuid4(),
        company_id=company.id,
        email="daria@pik.demo",
        password_hash=hash_password("demo"),
        role="hr",
        first_name="Дарья",
        last_name="Соколова",
        preferred_language="ru",
    )
    db_session.add(hr_user)
    await db_session.flush()

    return {"company": company, "hr_user": hr_user}


# ---------------------------------------------------------------------------
# hr_token — a valid HR JWT (unit-level, no DB required)
# ---------------------------------------------------------------------------


@pytest.fixture()
def hr_token(env_vars: dict) -> str:
    """Encode a valid HR JWT with role=hr for a deterministic company_id."""
    from app.auth.jwt import encode_jwt  # type: ignore[import]

    payload = {
        "sub": str(uuid.uuid4()),
        "role": "hr",
        "company_id": str(uuid.uuid4()),
    }
    return encode_jwt(payload)


# ---------------------------------------------------------------------------
# valid_invite — an Invite ORM row + raw HMAC token
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def valid_invite(db_session, seed_hr, env_vars):  # noqa: ANN001
    """Insert an Invite row for raju@example.com into the test DB.

    Returns dict with keys: raw_token, invite_id, company_id.
    """
    from app.db.models import Invite  # type: ignore[import]
    from app.auth.invite import sign_invite  # type: ignore[import]
    import hashlib

    company = seed_hr["company"]
    invite_id = uuid.uuid4()
    company_id = company.id

    payload = {
        "invite_id": str(invite_id),
        "email": "raju@example.com",
        "company_id": str(company_id),
    }
    raw_token = sign_invite(payload)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    invite = Invite(
        id=invite_id,
        company_id=company_id,
        email="raju@example.com",
        first_name="Раджу",
        last_name="Шарма",
        preferred_language="hi",
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(invite)
    await db_session.flush()

    return {
        "raw_token": raw_token,
        "invite_id": invite_id,
        "company_id": company_id,
        "invite": invite,
    }


# ---------------------------------------------------------------------------
# client_authed_as_hr — AsyncClient with HR Authorization header
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def client_authed_as_hr(app_client, seed_hr, env_vars):  # noqa: ANN001
    """app_client pre-authenticated as Дарья HR via login endpoint."""
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "daria@pik.demo", "password": "demo"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    app_client.headers.update({"Authorization": f"Bearer {token}"})
    return app_client


# ---------------------------------------------------------------------------
# tampered_jwt — valid JWT with flipped payload segment
# ---------------------------------------------------------------------------


@pytest.fixture()
def tampered_jwt(env_vars: dict) -> str:
    """Return a JWT string whose payload segment role has been flipped.

    The signature remains original so the verification MUST fail.
    """
    from app.auth.jwt import encode_jwt  # type: ignore[import]

    payload = {
        "sub": str(uuid.uuid4()),
        "role": "hr",
        "company_id": str(uuid.uuid4()),
    }
    token = encode_jwt(payload)

    parts = token.split(".")
    # Decode payload, flip role, re-encode without re-signing
    pad = "=" * (-len(parts[1]) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    decoded["role"] = "migrant"
    new_payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(decoded).encode()).rstrip(b"=").decode()
    )
    # Keep original signature → signature mismatch
    return f"{parts[0]}.{new_payload_b64}.{parts[2]}"


# ---------------------------------------------------------------------------
# db_session_with_users — two migrant users: one new, one old
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def db_session_with_users(db_session, seed_hr, env_vars):  # noqa: ANN001
    """Insert two migrant users: one created 60s ago ('new'), one 2 hours ago ('old').

    Returns dict:
        since_ts  : ISO8601 timestamp between old and new
        new_user  : the recent User ORM object
        old_user  : the older User ORM object
        company   : the ГК ПИК Company
    """
    from app.db.models import User  # type: ignore[import]

    company = seed_hr["company"]

    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=90)  # midpoint between old and new

    new_user = User(
        id=uuid.uuid4(),
        company_id=company.id,
        email=f"new-migrant-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=None,
        role="migrant",
        first_name="Раджу",
        last_name="Шарма",
        preferred_language="hi",
        created_at=now - timedelta(seconds=30),  # 30s ago → newer than since
    )
    old_user = User(
        id=uuid.uuid4(),
        company_id=company.id,
        email=f"old-migrant-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=None,
        role="migrant",
        first_name="Старый",
        last_name="Мигрант",
        preferred_language="ru",
        created_at=now - timedelta(hours=2),  # 2h ago → older than since
    )
    db_session.add(new_user)
    db_session.add(old_user)
    await db_session.flush()

    return {
        "since_ts": since.isoformat(),
        "new_user": new_user,
        "old_user": old_user,
        "company": company,
    }
