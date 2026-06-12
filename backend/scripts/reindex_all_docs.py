"""One-off maintenance: re-embed EVERY document (employer + sber global).

Run after an embedder change (e.g. ё→е/casefold normalization) that makes all
existing ChromaDB passage vectors stale. Reads each document from its persisted
storage_path, re-chunks, re-embeds with the CURRENT embedder, and upserts —
deleting stale chunks first. No JWT/company filter: covers all tenants + the
global partner_products collection in one pass.

    docker exec infra-api-1 python -m scripts.reindex_all_docs
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.api.v1.documents import _reindex_one
from app.config import get_settings
from app.database import async_session_factory
from app.db.models import Document


async def main() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        docs = list((await session.execute(select(Document))).scalars().all())
        print(f"reindex_all_docs: {len(docs)} documents found")
        ok = 0
        fail = 0
        for d in docs:
            scope = "partner" if d.is_partner_global else str(d.company_id)
            chunks_count, status = await _reindex_one(d, settings.chroma_persist_path)
            print(f"  [{status}] {d.name} ({scope}) — {chunks_count} chunks")
            if status == "indexed":
                ok += 1
            else:
                fail += 1
        print(f"reindex_all_docs: done — {ok} indexed, {fail} failed")


if __name__ == "__main__":
    asyncio.run(main())
