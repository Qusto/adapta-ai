"""Phase 10 — onboarding journey + personal documents single source of truth.

Verifies: migrant sees default 1/8 journey and 0/7 docs; uploading a doc
auto-advances the linked step; HR sees the SAME state for that worker; the
migrant chat-history endpoint returns the full thread (incl. role='hr').
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def _make_company_hr_migrant(db_session):  # noqa: ANN001
    from app.auth.password import hash_password
    from app.db.models import Company, User

    company = Company(id=uuid.uuid4(), name="Застройщик№1", inn="7700000001")
    db_session.add(company)
    await db_session.flush()

    hr = User(
        id=uuid.uuid4(),
        company_id=company.id,
        email=f"hr-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("demo"),
        role="hr",
        first_name="Дарья",
        last_name="Соколова",
        preferred_language="ru",
    )
    migrant = User(
        id=uuid.uuid4(),
        company_id=company.id,
        email=f"migrant-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=None,
        role="migrant",
        first_name="Альфари",
        last_name="Гамабджи",
        preferred_language="ru",
    )
    db_session.add(hr)
    db_session.add(migrant)
    await db_session.flush()
    return company, hr, migrant


def _token(user) -> str:  # noqa: ANN001
    from app.auth.jwt import encode_jwt

    return encode_jwt(
        {"sub": str(user.id), "role": user.role, "company_id": str(user.company_id)}
    )


@pytest.mark.asyncio
async def test_journey_single_source_of_truth(
    app_client, db_session, env_vars  # noqa: ANN001
) -> None:
    company, hr, migrant = await _make_company_hr_migrant(db_session)
    await db_session.commit()

    m_tok = _token(migrant)
    hr_tok = _token(hr)
    mh = {"Authorization": f"Bearer {m_tok}"}
    hh = {"Authorization": f"Bearer {hr_tok}"}

    # Fresh migrant: 1/8 journey, 0/7 docs
    r = await app_client.get("/api/v1/me/onboarding", headers=mh)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["done"] == 1 and body["total"] == 8
    assert body["steps"][0]["key"] == "arrived" and body["steps"][0]["status"] == "done"

    r = await app_client.get("/api/v1/me/documents", headers=mh)
    assert r.status_code == 200, r.text
    assert r.json()["uploaded"] == 0 and r.json()["required"] == 7

    # Upload SNILS → uploaded 1/7 AND onboarding step 'snils' becomes done (2/8)
    r = await app_client.post(
        "/api/v1/me/documents",
        headers=mh,
        json={"type": "snils", "number": "123-456-789 00"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["uploaded"] == 1

    r = await app_client.get("/api/v1/me/onboarding", headers=mh)
    assert r.json()["done"] == 2
    snils_step = next(s for s in r.json()["steps"] if s["key"] == "snils")
    assert snils_step["status"] == "done"

    # HR sees the SAME journey/docs for that worker (single source of truth)
    r = await app_client.get(f"/api/v1/workers/{migrant.id}/onboarding", headers=hh)
    assert r.status_code == 200, r.text
    assert r.json()["done"] == 2

    r = await app_client.get(f"/api/v1/workers/{migrant.id}/documents", headers=hh)
    assert r.status_code == 200
    assert r.json()["uploaded"] == 1

    # HR moves a step manually
    r = await app_client.patch(
        f"/api/v1/workers/{migrant.id}/onboarding/inn",
        headers=hh,
        json={"status": "in_progress"},
    )
    assert r.status_code == 200, r.text
    inn_step = next(s for s in r.json()["steps"] if s["key"] == "inn")
    assert inn_step["status"] == "in_progress"


@pytest.mark.asyncio
async def test_chat_history_returns_full_thread(
    app_client, db_session, env_vars  # noqa: ANN001
) -> None:
    from app.db.models import AiMessage

    _company, _hr, migrant = await _make_company_hr_migrant(db_session)
    # Seed a user question, an agent answer, and an HR reply
    for role, text in [("user", "test"), ("agent", "N/A"), ("hr", "Привет")]:
        db_session.add(AiMessage(user_id=migrant.id, role=role, text=text, language="ru"))
    await db_session.commit()

    mh = {"Authorization": f"Bearer {_token(migrant)}"}
    r = await app_client.get("/api/v1/me/chat/history", headers=mh)
    assert r.status_code == 200, r.text
    roles = [it["role"] for it in r.json()["items"]]
    assert "hr" in roles, f"HR reply must reach the migrant: {roles}"
    assert roles == ["user", "agent", "hr"]
