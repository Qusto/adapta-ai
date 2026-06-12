"""Seed partner-products RAG data — reads all markdown files from source_docs/.

Idempotent: re-running this script does not duplicate chunks in ChromaDB.
Each document is identified by its frontmatter ``product_id`` field; if a
document with the same product_id already exists in ChromaDB it is
re-indexed (upsert is safe).

Reads DATABASE_URL and CHROMA_PERSIST_PATH from the environment (same as
other scripts in this directory — no dependency on app.config.Settings so
the script runs even without GigaChat/OpenRouter keys).

Usage:
    python -m scripts.seed_partner_products          # seed once
    CHROMA_PERSIST_PATH=/custom/path python -m scripts.seed_partner_products
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger("scripts.seed_partner_products")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PIK_COMPANY_ID: uuid.UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_PARTNER_ADMIN_USER_ID: uuid.UUID = uuid.UUID("55555555-5555-5555-5555-555555555555")
_PARTNER_ADMIN_EMAIL: str = "partner-admin@adapta.demo"

_DMS_DOC_ID: uuid.UUID = uuid.UUID("66666666-6666-6666-6666-666666666666")
_DMS_DOC_NAME: str = "partner_dms_migrant.md"

# Fixed UUIDs for additional products (deterministic seeding)
_PRODUCT_DOC_IDS: dict[str, uuid.UUID] = {
    "partner_dms_migrant.md": uuid.UUID("66666666-6666-6666-6666-666666666666"),
    "partner_card_migrant.md": uuid.UUID("77777777-7777-7777-7777-777777777771"),
    "partner_mobile_migrant.md": uuid.UUID("77777777-7777-7777-7777-777777777772"),
    "partner_deposit_nonresident.md": uuid.UUID("77777777-7777-7777-7777-777777777773"),
    "partner_prime_zarplatnyi.md": uuid.UUID("77777777-7777-7777-7777-777777777774"),
    "partner_health_migrant.md": uuid.UUID("77777777-7777-7777-7777-777777777775"),
    "kuper_migrant.md": uuid.UUID("77777777-7777-7777-7777-777777777776"),
}

# ---------------------------------------------------------------------------
# Source docs discovery
# ---------------------------------------------------------------------------

_ENV_DIR = os.environ.get("ADAPTA_SOURCE_DOCS_DIR")
_CANDIDATES = (
    [Path(_ENV_DIR)]
    if _ENV_DIR
    else [
        Path(__file__).parent.parent.parent / "data" / "rag_eval" / "source_docs",  # local: backend/scripts → repo root
        Path(__file__).parent.parent / "data" / "rag_eval" / "source_docs",          # container: /app/scripts → /app/data
        Path("/app/data/rag_eval/source_docs"),                                       # absolute fallback in container
    ]
)
_SOURCE_DOCS_DIR = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[-1])


def _discover_source_docs() -> list[Path]:
    """Return all partner_*.md and kuper_*.md files from source_docs/."""
    if not _SOURCE_DOCS_DIR.exists():
        logger.warning("source_docs dir not found: %s", _SOURCE_DOCS_DIR)
        return []
    docs: list[Path] = []
    for pattern in ("partner_*.md", "kuper_*.md"):
        docs.extend(sorted(_SOURCE_DOCS_DIR.glob(pattern)))
    return docs


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter block (between first two '---' lines).

    Returns (metadata_dict, body_without_frontmatter).
    If no frontmatter found, returns ({}, content).
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, content

    fm_lines = lines[1:end_idx]
    meta: dict[str, str] = {}
    for fm_line in fm_lines:
        if ":" in fm_line:
            key, _, value = fm_line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")

    body = "\n".join(lines[end_idx + 1:]).strip()
    return meta, body


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _get_chroma_path() -> str:
    return os.environ.get("CHROMA_PERSIST_PATH", "./data/chromadb")


async def _ensure_partner_admin(session: AsyncSession) -> None:
    """Create a placeholder partner-admin user if needed (for uploaded_by FK)."""
    existing = (
        await session.execute(
            text("SELECT id FROM users WHERE id = :id"),
            {"id": _PARTNER_ADMIN_USER_ID},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    # Ensure Застройщик№1 company exists (reuse PIK for seed simplicity)
    company_exists = (
        await session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": _PIK_COMPANY_ID},
        )
    ).scalar_one_or_none()
    if company_exists is None:
        await session.execute(
            text("INSERT INTO companies (id, name, inn) VALUES (:id, :name, :inn)"),
            {"id": _PIK_COMPANY_ID, "name": "Застройщик№1", "inn": "7700000001"},
        )
        logger.info("created company Застройщик№1")

    await session.execute(
        text(
            "INSERT INTO users (id, company_id, email, password_hash, role, "
            "first_name, last_name, preferred_language) "
            "VALUES (:id, :company_id, :email, NULL, :role, :fn, :ln, :lang)"
        ),
        {
            "id": _PARTNER_ADMIN_USER_ID,
            "company_id": _PIK_COMPANY_ID,
            "email": _PARTNER_ADMIN_EMAIL,
            "role": "hr",
            "fn": "Partner",
            "ln": "Admin",
            "lang": "ru",
        },
    )
    logger.info("created partner-admin user id=%s", _PARTNER_ADMIN_USER_ID)


async def _ensure_document_record(
    session: AsyncSession,
    doc_id: uuid.UUID,
    doc_name: str,
    storage_path: str,
    content: str,
) -> bool:
    """Insert document row if absent. Returns True if newly created."""
    existing = (
        await session.execute(
            text("SELECT id FROM documents WHERE id = :id"),
            {"id": doc_id},
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info("Document record already present for %s — skip Postgres insert", doc_name)
        return False

    await session.execute(
        text(
            "INSERT INTO documents (id, company_id, uploaded_by, name, mime_type, "
            "size_bytes, storage_path, status, chunks_count, is_partner_global) "
            "VALUES (:id, :cid, :uid, :name, :mime, :size, :path, :status, 0, true)"
        ),
        {
            "id": doc_id,
            "cid": _PIK_COMPANY_ID,
            "uid": _PARTNER_ADMIN_USER_ID,
            "name": doc_name,
            "mime": "text/markdown",
            "size": len(content.encode("utf-8")),
            "path": storage_path,
            "status": "processing",
        },
    )
    logger.info("inserted document record id=%s name=%s", doc_id, doc_name)
    return True


async def _update_document_status(
    session: AsyncSession, doc_id: uuid.UUID, chunks_count: int
) -> None:
    await session.execute(
        text(
            "UPDATE documents SET status='indexed', chunks_count=:n WHERE id=:id"
        ),
        {"n": chunks_count, "id": doc_id},
    )


# ---------------------------------------------------------------------------
# ChromaDB indexing
# ---------------------------------------------------------------------------


def _index_document_to_chroma(
    chroma_path: str,
    file_name: str,
    content: str,
    meta: dict[str, str],
) -> int:
    """Index document content into partner_products ChromaDB collection.

    Returns chunk count indexed.
    """
    import chromadb  # noqa: PLC0415

    from app.rag.chunker import chunk_document  # noqa: PLC0415
    from app.rag.factory import get_embedder  # noqa: PLC0415
    from app.rag.loader import LoadedDocument, PageContent  # noqa: PLC0415
    from app.rag.store import PARTNER_PRODUCTS_COLLECTION  # noqa: PLC0415

    loaded = LoadedDocument(
        file_name=file_name,
        pages=[PageContent(text=content, page_number=1)],
    )
    chunks = chunk_document(loaded)
    if not chunks:
        logger.warning("No chunks produced from %s — check chunker config", file_name)
        return 0

    embedder = get_embedder()
    texts = [c.text for c in chunks]
    embeddings = embedder.embed_passages(texts)

    client = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_or_create_collection(
        name=PARTNER_PRODUCTS_COLLECTION,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )

    product_id = meta.get("product_id", file_name.rsplit(".", 1)[0])
    product_title = meta.get("product_title", file_name.rsplit(".", 1)[0].replace("_", " "))
    product_subtitle = meta.get("product_subtitle", "")
    product_badge = meta.get("product_badge", "")
    product_url = meta.get("product_url", "")
    language = meta.get("language", "ru")
    collection_name = meta.get("collection", PARTNER_PRODUCTS_COLLECTION)

    ids = [f"{file_name}::{c.chunk_idx}" for c in chunks]
    documents = [c.text for c in chunks]
    metadatas: list[dict[str, Any]] = [
        {
            "file_name": file_name,
            "chunk_idx": c.chunk_idx,
            "page": c.page if c.page is not None else -1,
            "language": language,
            "collection": collection_name,
            "snippet": c.text[:200],
            "product_id": product_id,
            "product_title": product_title,
            "product_subtitle": product_subtitle,
            "product_badge": product_badge,
            "product_url": product_url,
            # Legacy field names kept for backwards compat with message_handler
            "title": product_title,
            "subtitle": product_subtitle,
            "badge": product_badge,
            "url": product_url,
        }
        for c in chunks
    ]

    collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    logger.info(
        "Indexed %d chunks for '%s' (product_id=%s) into collection '%s' at %s",
        len(chunks),
        file_name,
        product_id,
        PARTNER_PRODUCTS_COLLECTION,
        chroma_path,
    )
    return len(chunks)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    db_url = _get_database_url()
    chroma_path = _get_chroma_path()

    uploads_dir = Path(os.environ.get("UPLOADS_PATH", "./data/uploads"))
    uploads_dir.mkdir(parents=True, exist_ok=True)

    source_docs = _discover_source_docs()
    if not source_docs:
        logger.error(
            "No source documents found in %s — ensure partner_*.md / kuper_*.md files exist",
            _SOURCE_DOCS_DIR,
        )
        return

    logger.info("Found %d source documents to index", len(source_docs))

    engine = create_async_engine(db_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_chunks = 0
    try:
        async with session_factory() as session:
            async with session.begin():
                await _ensure_partner_admin(session)

        for doc_path in source_docs:
            file_name = doc_path.name
            content = doc_path.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(content)

            # Use body-only content for chunking so frontmatter isn't indexed
            index_content = body if body else content

            storage_path = str(uploads_dir / file_name)
            Path(storage_path).write_text(index_content, encoding="utf-8")
            logger.info("Written content to %s", storage_path)

            doc_id = _PRODUCT_DOC_IDS.get(
                file_name,
                uuid.uuid5(uuid.NAMESPACE_DNS, f"adapta.{file_name}"),
            )

            async with session_factory() as session:
                async with session.begin():
                    await _ensure_document_record(
                        session, doc_id, file_name, storage_path, index_content
                    )

            chunks_count = _index_document_to_chroma(
                chroma_path, file_name, index_content, meta
            )
            total_chunks += chunks_count

            async with session_factory() as session:
                async with session.begin():
                    await _update_document_status(session, doc_id, chunks_count)

        logger.info(
            "seed_partner_products OK — %d documents, %d total chunks indexed",
            len(source_docs),
            total_chunks,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
