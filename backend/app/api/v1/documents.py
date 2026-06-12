"""Documents API — Phase 2 + Phase 3.5 bugfix wave.

POST   /api/v1/documents/upload         — HR-only, multipart PDF/DOCX upload → RAG index
GET    /api/v1/documents                — HR-only, list company documents
DELETE /api/v1/documents/{id}           — HR-only, remove DB row + ChromaDB chunks + file
POST   /api/v1/documents/{id}/reindex   — HR-only, re-chunk + re-embed an existing file
POST   /api/v1/documents/reindex-all    — HR-only, reindex every company doc in one call
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import pathlib
import tempfile
import uuid
from datetime import datetime
from typing import Annotated

import chromadb
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_hr
from app.config import get_settings
from app.database import async_session_factory
from app.db.models import Document, User
from app.rag.chunker import Chunk, chunk_document
from app.rag.factory import get_embedder, get_store
from app.rag.loader import LoadedDocument, PageContent, load_docx, load_pdf
from app.rag.store import PARTNER_PRODUCTS_COLLECTION, PartnerProductsStore, get_partner_products_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx"}
_MAX_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
_CHROMA_COLLECTION = "employer_docs_demo"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DocumentResponse(BaseModel):
    """Single document metadata response."""

    id: uuid.UUID
    name: str
    mime_type: str
    size_bytes: int
    status: str
    chunks_count: int
    is_partner_global: bool = False
    created_at: datetime


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    items: list[DocumentResponse]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_mime(filename: str, content_type: str | None) -> str:
    """Determine MIME type from filename extension."""
    ext = pathlib.Path(filename).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return content_type or "application/octet-stream"


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _make_error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


def _orm_to_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        name=doc.name,
        mime_type=doc.mime_type,
        size_bytes=doc.size_bytes,
        status=doc.status,
        chunks_count=doc.chunks_count,
        is_partner_global=doc.is_partner_global,
        created_at=doc.created_at,
    )


async def _find_existing_document(
    session: AsyncSession,
    company_id: uuid.UUID,
    file_name: str,
) -> Document | None:
    """Find an existing document by company_id + name."""
    q = select(Document).where(
        Document.company_id == company_id,
        Document.name == file_name,
    )
    result = await session.execute(q)
    return result.scalar_one_or_none()


def _read_storage_file(storage_path: str) -> bytes:
    """Read file from storage, return empty bytes if missing."""
    p = pathlib.Path(storage_path)
    return p.read_bytes() if p.exists() else b""


def _delete_chroma_chunks(
    persist_dir: str,
    file_name: str,
    collection_name: str = _CHROMA_COLLECTION,
) -> None:
    """Delete all ChromaDB chunks for the given file_name in the given collection."""
    try:
        client = chromadb.PersistentClient(path=persist_dir)
        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )
        collection.delete(where={"file_name": file_name})
        logger.info(
            "Deleted chroma chunks for file_name=%s collection=%s",
            file_name,
            collection_name,
        )
    except Exception as exc:
        logger.warning("Failed to delete chroma chunks: %s", exc)


def _load_chunks_from_content(
    content: bytes,
    file_name: str,
    ext: str,
) -> list[Chunk]:
    """Parse content bytes, chunk it, and return chunks.

    Markdown files are loaded directly from bytes (no temp file).
    PDF and DOCX are written to a temp file then parsed.
    """
    if ext in (".md", ".markdown"):
        text = content.decode("utf-8")
        # Strip YAML frontmatter (--- ... ---) so it doesn't pollute chunks.
        lines = text.splitlines()
        if lines and lines[0].strip() == "---":
            end_idx: int | None = None
            for i, line in enumerate(lines[1:], start=1):
                if line.strip() == "---":
                    end_idx = i
                    break
            if end_idx is not None:
                body = "\n".join(lines[end_idx + 1:]).strip()
                text = body if body else text
        loaded = LoadedDocument(
            file_name=file_name,
            pages=[PageContent(text=text, page_number=1)],
        )
        return chunk_document(loaded)

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = pathlib.Path(tmp.name)

    target_path = tmp_path.parent / file_name
    tmp_path.rename(target_path)

    try:
        if ext == ".pdf":
            loaded = load_pdf(target_path)
        else:
            loaded = load_docx(target_path)
    finally:
        target_path.unlink(missing_ok=True)

    return chunk_document(loaded)


def _index_document_sync(
    content: bytes,
    file_name: str,
    ext: str,
    company_id: str,
    persist_dir: str,
) -> int:
    """Parse → chunk → embed → store (employer collection). Returns chunks_count."""
    chunks = _load_chunks_from_content(content, file_name, ext)
    if not chunks:
        return 0

    embedder = get_embedder()
    texts = [c.text for c in chunks]
    embeddings = embedder.embed_passages(texts)

    store = get_store()
    store.upsert(
        chunks=chunks,
        embeddings=embeddings,
        company_id=company_id,
        language="ru",
    )

    return len(chunks)


def _index_partner_products_sync(
    content: bytes,
    file_name: str,
    ext: str,
    persist_dir: str,
) -> int:
    """Parse → chunk → embed → store (partner_products collection). Returns chunks_count."""
    chunks = _load_chunks_from_content(content, file_name, ext)
    if not chunks:
        return 0

    embedder = get_embedder()
    texts = [c.text for c in chunks]
    embeddings = embedder.embed_passages(texts)

    partner_store: PartnerProductsStore = get_partner_products_store()
    partner_store.upsert(
        chunks=chunks,
        embeddings=embeddings,
        language="ru",
    )

    return len(chunks)


# ---------------------------------------------------------------------------
# POST /documents/upload
# ---------------------------------------------------------------------------


async def _handle_idempotency(
    session: AsyncSession,
    company_id: uuid.UUID,
    file_name: str,
    doc_hash: str,
    chroma_persist_path: str,
) -> DocumentResponse | None:
    """Check for existing document; return response if same hash, delete if changed."""
    existing = await _find_existing_document(session, company_id, file_name)
    if existing is None:
        return None

    existing_hash = _sha256_bytes(_read_storage_file(existing.storage_path))
    if existing_hash == doc_hash:
        logger.info("Document %s already indexed (same hash)", file_name)
        return _orm_to_response(existing)

    logger.info("Document %s changed hash, re-indexing", file_name)
    _delete_chroma_chunks(chroma_persist_path, file_name)
    await session.delete(existing)
    await session.commit()
    return None


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    current_user: Annotated[User, Depends(require_hr)],
    collection: str = Query(
        default="employer_docs",
        description="Target collection: 'employer_docs' or 'partner_products'",
    ),
) -> DocumentResponse:
    """Upload a PDF or DOCX file and index it in ChromaDB.

    - Auth: JWT role=hr
    - Idempotent by file_name + doc_hash
    - collection=partner_products → indexes into the global partner-products collection
    """
    settings = get_settings()
    is_partner = collection == PARTNER_PRODUCTS_COLLECTION

    filename = file.filename or "upload"
    ext = pathlib.Path(filename).suffix.lower()
    mime_type = _detect_mime(filename, file.content_type)

    if ext not in _ALLOWED_EXTENSIONS or mime_type not in _ALLOWED_MIME_TYPES:
        raise _make_error(
            "VALIDATION_ERROR",
            f"Unsupported file type '{ext}'. Only PDF and DOCX are accepted.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    content = await file.read()
    size_bytes = len(content)

    if size_bytes > _MAX_SIZE_BYTES:
        raise _make_error(
            "VALIDATION_ERROR",
            f"File size {size_bytes} exceeds 10 MB limit.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    doc_hash = _sha256_bytes(content)

    async with async_session_factory() as session:
        maybe_existing = await _handle_idempotency(
            session,
            current_user.company_id,
            filename,
            doc_hash,
            settings.chroma_persist_path,
        )
        if maybe_existing is not None:
            return maybe_existing

    doc_id = uuid.uuid4()
    storage_dir = pathlib.Path(settings.uploads_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = str(storage_dir / f"{doc_id}{ext}")
    pathlib.Path(storage_path).write_bytes(content)

    async with async_session_factory() as session:
        doc = Document(
            id=doc_id,
            company_id=current_user.company_id,
            uploaded_by=current_user.id,
            name=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            status="processing",
            chunks_count=0,
            is_partner_global=is_partner,
        )
        session.add(doc)
        await session.commit()

    try:
        if is_partner:
            chunks_count = _index_partner_products_sync(
                content=content,
                file_name=filename,
                ext=ext,
                persist_dir=settings.chroma_persist_path,
            )
        else:
            chunks_count = _index_document_sync(
                content=content,
                file_name=filename,
                ext=ext,
                company_id=str(current_user.company_id),
                persist_dir=settings.chroma_persist_path,
            )
    except Exception as exc:
        logger.error("Indexing failed for %s: %s", filename, exc, exc_info=True)
        async with async_session_factory() as session:
            doc_to_fail = await session.get(Document, doc_id)
            if doc_to_fail is not None:
                doc_to_fail.status = "failed"
                await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"code": "INTERNAL_ERROR", "message": "Indexing failed."}},
        ) from exc

    async with async_session_factory() as session:
        doc_obj = await session.get(Document, doc_id)
        if doc_obj is not None:
            doc_obj.status = "indexed"
            doc_obj.chunks_count = chunks_count
            await session.commit()
            await session.refresh(doc_obj)
            return _orm_to_response(doc_obj)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": {"code": "INTERNAL_ERROR", "message": "Document record lost."}},
    )


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_documents(
    current_user: Annotated[User, Depends(require_hr)],
    limit: int = 50,
    offset: int = 0,
    collection: str = Query(
        default="employer_docs",
        description="'employer_docs' or 'partner_products'",
    ),
) -> DocumentListResponse:
    """List documents.

    - Auth: JWT role=hr
    - collection=partner_products → lists all partner-product docs (global)
    - Default: company-scoped employer docs
    """
    is_partner = collection == PARTNER_PRODUCTS_COLLECTION

    async with async_session_factory() as session:
        if is_partner:
            count_q = select(func.count(Document.id)).where(
                Document.is_partner_global.is_(True)
            )
            list_q = (
                select(Document)
                .where(Document.is_partner_global.is_(True))
                .order_by(Document.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        else:
            count_q = select(func.count(Document.id)).where(
                Document.company_id == current_user.company_id,
                Document.is_partner_global.is_(False),
            )
            list_q = (
                select(Document)
                .where(
                    Document.company_id == current_user.company_id,
                    Document.is_partner_global.is_(False),
                )
                .order_by(Document.created_at.desc())
                .limit(limit)
                .offset(offset)
            )

        total_result = await session.execute(count_q)
        total: int = total_result.scalar() or 0

        result = await session.execute(list_q)
        docs = list(result.scalars().all())

    return DocumentListResponse(items=[_orm_to_response(d) for d in docs], total=total)


# ---------------------------------------------------------------------------
# DELETE /documents/{id}
# ---------------------------------------------------------------------------


class DeleteDocumentResponse(BaseModel):
    """Response envelope for a successful delete."""

    id: uuid.UUID
    deleted: bool = True
    chunks_deleted: int


@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_hr)],
) -> DeleteDocumentResponse:
    """Remove a document from Postgres + ChromaDB + local storage.

    - Auth: JWT role=hr
    - 404 if document does not exist or belongs to another company
    - Idempotent: subsequent calls on the same id return 404
    """
    settings = get_settings()

    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        # Allow deletion if: doc is partner_global (any HR), or doc belongs to user's company
        if doc is None or (not doc.is_partner_global and doc.company_id != current_user.company_id):
            raise _make_error(
                "NOT_FOUND",
                f"Document {document_id} not found.",
                status.HTTP_404_NOT_FOUND,
            )

        file_name = doc.name
        storage_path = doc.storage_path
        chunks_count = doc.chunks_count
        doc_is_partner = doc.is_partner_global

        await session.delete(doc)
        await session.commit()

    # Best-effort cleanup of vectors + storage (Postgres is the source of truth).
    chroma_collection = PARTNER_PRODUCTS_COLLECTION if doc_is_partner else _CHROMA_COLLECTION
    _delete_chroma_chunks(settings.chroma_persist_path, file_name, chroma_collection)
    try:
        path = pathlib.Path(storage_path)
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("Failed to remove file %s: %s", storage_path, exc)

    return DeleteDocumentResponse(id=document_id, chunks_deleted=chunks_count)


# ---------------------------------------------------------------------------
# POST /documents/{id}/reindex  and  POST /documents/reindex-all
# ---------------------------------------------------------------------------


class ReindexResponse(BaseModel):
    """Response for single-document reindex."""

    id: uuid.UUID
    name: str
    chunks_count: int
    status: str


class ReindexAllResponse(BaseModel):
    """Response for bulk reindex."""

    reindexed: int
    failed: int
    total: int


async def _reindex_one(doc: Document, persist_dir: str) -> tuple[int, str]:
    """Re-run parse → chunk → embed → upsert for a single document.

    Returns (chunks_count, status). Status is 'indexed' on success, 'failed' on error.
    Handles both employer_docs and partner_products collections.
    """
    ext = pathlib.Path(doc.name).suffix.lower()
    storage_path = pathlib.Path(doc.storage_path)
    if not storage_path.exists():
        logger.error("Reindex aborted: file missing at %s", storage_path)
        return (0, "failed")

    content = storage_path.read_bytes()
    is_partner = doc.is_partner_global

    # Clear stale vectors before re-upserting so chunk count reflects reality.
    chroma_coll = PARTNER_PRODUCTS_COLLECTION if is_partner else _CHROMA_COLLECTION
    _delete_chroma_chunks(persist_dir, doc.name, chroma_coll)

    try:
        if is_partner:
            chunks_count = await asyncio.to_thread(
                _index_partner_products_sync,
                content,
                doc.name,
                ext,
                persist_dir,
            )
        else:
            chunks_count = await asyncio.to_thread(
                _index_document_sync,
                content,
                doc.name,
                ext,
                str(doc.company_id),
                persist_dir,
            )
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("Reindex failed for %s: %s", doc.name, exc, exc_info=True)
        return (0, "failed")

    return (chunks_count, "indexed")


@router.post("/{document_id}/reindex", status_code=status.HTTP_200_OK)
async def reindex_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_hr)],
) -> ReindexResponse:
    """Re-chunk + re-embed an existing document. Preserves the same row id.

    - Auth: JWT role=hr
    - 404 if document does not exist or belongs to another company
    """
    settings = get_settings()

    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None or (not doc.is_partner_global and doc.company_id != current_user.company_id):
            raise _make_error(
                "NOT_FOUND",
                f"Document {document_id} not found.",
                status.HTTP_404_NOT_FOUND,
            )
        # Mark processing for the duration of the reindex
        doc.status = "processing"
        await session.commit()
        # Capture the fields we need before the session closes so we don't
        # touch a detached ORM object while the reindex runs.
        doc_snapshot = Document(
            id=doc.id,
            company_id=doc.company_id,
            uploaded_by=doc.uploaded_by,
            name=doc.name,
            mime_type=doc.mime_type,
            size_bytes=doc.size_bytes,
            storage_path=doc.storage_path,
            status="processing",
            chunks_count=doc.chunks_count,
            is_partner_global=doc.is_partner_global,
        )
        doc_name = doc.name

    chunks_count, new_status = await _reindex_one(
        doc=doc_snapshot,
        persist_dir=settings.chroma_persist_path,
    )

    async with async_session_factory() as session:
        doc_obj = await session.get(Document, document_id)
        if doc_obj is None:
            raise _make_error(
                "NOT_FOUND",
                f"Document {document_id} disappeared during reindex.",
                status.HTTP_404_NOT_FOUND,
            )
        doc_obj.status = new_status
        doc_obj.chunks_count = chunks_count
        await session.commit()
        return ReindexResponse(
            id=document_id,
            name=doc_name,
            chunks_count=chunks_count,
            status=new_status,
        )


@router.post("/reindex-all", status_code=status.HTTP_200_OK)
async def reindex_all_documents(
    current_user: Annotated[User, Depends(require_hr)],
) -> ReindexAllResponse:
    """Reindex every document belonging to the current HR's company.

    - Auth: JWT role=hr
    - Best-effort: a per-doc failure is logged and counted, not propagated.
    """
    settings = get_settings()

    async with async_session_factory() as session:
        list_q = select(Document).where(Document.company_id == current_user.company_id)
        result = await session.execute(list_q)
        docs = list(result.scalars().all())
        # Stage them all as processing up front so the UI reflects state.
        snapshots: list[Document] = []
        for d in docs:
            d.status = "processing"
            snapshots.append(
                Document(
                    id=d.id,
                    company_id=d.company_id,
                    uploaded_by=d.uploaded_by,
                    name=d.name,
                    mime_type=d.mime_type,
                    size_bytes=d.size_bytes,
                    storage_path=d.storage_path,
                    status="processing",
                    chunks_count=d.chunks_count,
                )
            )
        await session.commit()

    reindexed = 0
    failed = 0
    for snap in snapshots:
        chunks_count, new_status = await _reindex_one(snap, settings.chroma_persist_path)
        async with async_session_factory() as session:
            doc_obj = await session.get(Document, snap.id)
            if doc_obj is not None:
                doc_obj.status = new_status
                doc_obj.chunks_count = chunks_count
                await session.commit()
        if new_status == "indexed":
            reindexed += 1
        else:
            failed += 1

    return ReindexAllResponse(reindexed=reindexed, failed=failed, total=len(snapshots))
