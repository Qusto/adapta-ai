"""Integration tests for POST /api/v1/documents/upload and GET /api/v1/documents.

Phase 2 RAG: tests upload, listing, role enforcement, and format validation.
These tests use a real FastAPI app (ASGITransport), isolated chroma dir,
and a test Postgres container.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
import pytest_asyncio

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Local fixtures (self-contained, avoid pulling Phase 1 integration fixtures)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def db_with_hr(db_session, env_vars):
    """Insert ГК ПИК company + Дарья HR user for document tests."""
    from app.auth.password import hash_password
    from app.db.models import Company, User

    company = Company(
        id=uuid.uuid4(),
        name="ГК ПИК",
        inn=f"test-{uuid.uuid4().hex[:8]}",  # unique per test run
    )
    db_session.add(company)
    await db_session.flush()

    hr_user = User(
        id=uuid.uuid4(),
        company_id=company.id,
        email=f"hr-{uuid.uuid4().hex[:8]}@pik.test",
        password_hash=hash_password("demo"),
        role="hr",
        first_name="Дарья",
        last_name="Соколова",
        preferred_language="ru",
    )
    db_session.add(hr_user)
    await db_session.flush()

    return {"company": company, "hr_user": hr_user}


@pytest_asyncio.fixture()
async def hr_client(app_client, db_with_hr):
    """app_client authenticated as HR user via login."""
    hr_user = db_with_hr["hr_user"]
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": hr_user.email, "password": "demo"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    app_client.headers.update({"Authorization": f"Bearer {token}"})
    return app_client


@pytest.fixture()
def migrant_jwt(env_vars: dict) -> str:
    """JWT with role=migrant (no DB required)."""
    from app.auth.jwt import encode_jwt

    return encode_jwt(
        {
            "sub": str(uuid.uuid4()),
            "role": "migrant",
            "company_id": str(uuid.uuid4()),
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_upload_pdf_returns_document_with_chunks_count(
    hr_client,
    tmp_path,
) -> None:
    """POST /api/v1/documents/upload with PDF → 201, chunks_count > 0, status=indexed."""
    import app.config as config_module

    pdf_path = FIXTURES / "demo_ru.pdf"
    assert pdf_path.exists(), f"Fixture not found: {pdf_path}"

    # Override chroma + uploads path for isolation
    chroma_dir = str(tmp_path / "chroma")
    uploads_dir = str(tmp_path / "uploads")

    original_get_settings = config_module.get_settings

    def patched_settings():  # type: ignore[return]
        s = original_get_settings()
        object.__setattr__(s, "chroma_persist_path", chroma_dir)
        object.__setattr__(s, "uploads_path", uploads_dir)
        return s

    import app.api.v1.documents as docs_module

    original_module_get_settings = docs_module.get_settings
    docs_module.get_settings = patched_settings  # type: ignore[assignment]

    try:
        with open(pdf_path, "rb") as f:
            resp = await hr_client.post(
                "/api/v1/documents/upload",
                files={"file": ("demo_ru.pdf", f, "application/pdf")},
            )
    finally:
        docs_module.get_settings = original_module_get_settings

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "indexed", f"Expected indexed, got {body['status']}"
    assert body["chunks_count"] > 0, f"Expected chunks_count > 0, got {body['chunks_count']}"
    assert body["name"] == "demo_ru.pdf"
    assert "id" in body
    assert "created_at" in body


@pytest.mark.integration
async def test_list_documents_returns_company_docs(
    app_client,
    db_with_hr,
    env_vars,
    tmp_path,
) -> None:
    """GET /api/v1/documents → returns list including uploaded document."""
    import uuid as _uuid

    from app.database import async_session_factory
    from app.db.models import Document

    hr_user = db_with_hr["hr_user"]
    company = db_with_hr["company"]

    # Insert a document directly into DB
    doc_id = _uuid.uuid4()
    async with async_session_factory() as session:
        doc = Document(
            id=doc_id,
            company_id=company.id,
            uploaded_by=hr_user.id,
            name="test_doc.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            storage_path=str(tmp_path / "test_doc.pdf"),
            status="indexed",
            chunks_count=5,
        )
        session.add(doc)
        await session.commit()

    # Login as HR
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": hr_user.email, "password": "demo"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    app_client.headers.update({"Authorization": f"Bearer {token}"})

    resp = await app_client.get("/api/v1/documents")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 1

    doc_ids = [item["id"] for item in body["items"]]
    assert str(doc_id) in doc_ids, f"Uploaded doc {doc_id} not in list: {doc_ids}"


@pytest.mark.integration
async def test_upload_requires_hr_role(
    app_client,
    migrant_jwt: str,
    env_vars,
) -> None:
    """POST /api/v1/documents/upload with migrant JWT → 403."""
    pdf_path = FIXTURES / "demo_ru.pdf"
    assert pdf_path.exists()

    app_client.headers.update({"Authorization": f"Bearer {migrant_jwt}"})
    with open(pdf_path, "rb") as f:
        resp = await app_client.post(
            "/api/v1/documents/upload",
            files={"file": ("demo_ru.pdf", f, "application/pdf")},
        )

    assert resp.status_code == 403, (
        f"Expected 403 FORBIDDEN for migrant role, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.integration
async def test_upload_rejects_unsupported_format(
    hr_client,
    env_vars,
) -> None:
    """POST /api/v1/documents/upload with .txt file → 422 VALIDATION_ERROR."""
    fake_txt_content = b"This is a plain text file, not PDF or DOCX."

    resp = await hr_client.post(
        "/api/v1/documents/upload",
        files={"file": ("policy.txt", fake_txt_content, "text/plain")},
    )

    assert resp.status_code == 422, (
        f"Expected 422 for unsupported format, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    # Verify error envelope follows PRD §5
    assert "error" in body or "detail" in body


# ---------------------------------------------------------------------------
# DELETE / reindex tests (Bug #3, e2e UI sweep 2026-05-27)
# ---------------------------------------------------------------------------


def _patch_chroma_uploads(monkeypatch_target, tmp_path):
    """Patch get_settings so chroma + uploads point at tmp_path. Returns restore fn."""
    import app.api.v1.documents as docs_module
    import app.config as config_module

    chroma_dir = str(tmp_path / "chroma")
    uploads_dir = str(tmp_path / "uploads")
    original_get_settings = config_module.get_settings

    def patched():  # type: ignore[return]
        s = original_get_settings()
        object.__setattr__(s, "chroma_persist_path", chroma_dir)
        object.__setattr__(s, "uploads_path", uploads_dir)
        return s

    original_module_get_settings = docs_module.get_settings
    docs_module.get_settings = patched  # type: ignore[assignment]

    def restore() -> None:
        docs_module.get_settings = original_module_get_settings

    return restore


@pytest.mark.integration
@pytest.mark.slow
async def test_delete_document_removes_db_and_chroma(
    hr_client,
    tmp_path,
) -> None:
    """Upload a PDF → DELETE → list is empty → ChromaDB has no chunks for that file."""
    import chromadb

    pdf_path = FIXTURES / "demo_ru.pdf"
    assert pdf_path.exists()

    restore = _patch_chroma_uploads(None, tmp_path)
    try:
        # 1. Upload
        with open(pdf_path, "rb") as f:
            upload_resp = await hr_client.post(
                "/api/v1/documents/upload",
                files={"file": ("delete_me.pdf", f, "application/pdf")},
            )
        assert upload_resp.status_code == 201, upload_resp.text
        doc_id = upload_resp.json()["id"]

        # Sanity: list now has at least one doc
        list_resp = await hr_client.get("/api/v1/documents")
        assert list_resp.status_code == 200
        assert any(item["id"] == doc_id for item in list_resp.json()["items"])

        # 2. Delete
        del_resp = await hr_client.delete(f"/api/v1/documents/{doc_id}")
        assert del_resp.status_code == 200, del_resp.text
        body = del_resp.json()
        assert body["deleted"] is True
        assert body["id"] == doc_id

        # 3. Confirm DB row gone
        list_resp = await hr_client.get("/api/v1/documents")
        assert list_resp.status_code == 200
        assert not any(item["id"] == doc_id for item in list_resp.json()["items"])

        # 4. Confirm chroma has zero chunks for delete_me.pdf
        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        col = client.get_or_create_collection(
            name="employer_docs_demo",
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )
        chroma_get = col.get(where={"file_name": "delete_me.pdf"})
        assert not chroma_get.get("ids"), (
            f"Expected no chroma chunks for delete_me.pdf, got: {chroma_get['ids']}"
        )
    finally:
        restore()


@pytest.mark.integration
async def test_delete_returns_404_on_missing(
    hr_client,
) -> None:
    """DELETE with a non-existent UUID → 404 NOT_FOUND."""
    ghost_id = uuid.uuid4()
    resp = await hr_client.delete(f"/api/v1/documents/{ghost_id}")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    # Error envelope per PRD §5
    detail = body.get("detail", body)
    err = detail.get("error", {}) if isinstance(detail, dict) else {}
    assert err.get("code") == "NOT_FOUND" or "not found" in str(detail).lower()


@pytest.mark.integration
@pytest.mark.slow
async def test_reindex_one_keeps_id_changes_chunks(
    hr_client,
    tmp_path,
) -> None:
    """Reindex an existing doc → row id stays, chunks_count is refreshed."""
    pdf_path = FIXTURES / "demo_ru.pdf"
    assert pdf_path.exists()

    restore = _patch_chroma_uploads(None, tmp_path)
    try:
        # 1. Upload
        with open(pdf_path, "rb") as f:
            upload_resp = await hr_client.post(
                "/api/v1/documents/upload",
                files={"file": ("reindex_me.pdf", f, "application/pdf")},
            )
        assert upload_resp.status_code == 201, upload_resp.text
        body = upload_resp.json()
        doc_id = body["id"]
        original_chunks = body["chunks_count"]
        assert original_chunks > 0

        # 2. Reindex
        re_resp = await hr_client.post(f"/api/v1/documents/{doc_id}/reindex")
        assert re_resp.status_code == 200, re_resp.text
        re_body = re_resp.json()
        assert re_body["id"] == doc_id, "Reindex must preserve the row id"
        assert re_body["status"] == "indexed"
        # Same file → same chunk count
        assert re_body["chunks_count"] == original_chunks, (
            f"Expected stable chunk count {original_chunks}, got {re_body['chunks_count']}"
        )

        # 3. Reindex on a non-existent doc → 404
        ghost_id = uuid.uuid4()
        ghost_resp = await hr_client.post(f"/api/v1/documents/{ghost_id}/reindex")
        assert ghost_resp.status_code == 404
    finally:
        restore()
