"""Ingest the v2 domain knowledge docs into the chat RAG collection.

seed_partner_products.py only indexes partner_*/kuper_* into the `partner_products`
collection. The 17 domain docs of golden_dataset_v2 (employment_contract,
sim_card, money_transfer, safety, emergency, housing, work_patent, …) belong
in the `employer_docs_demo` collection so the dual-retriever finds them for the
demo migrant (Раджу, company ГК ПИК).

Idempotent: deletes a doc's existing chunks before re-upserting.

Run INSIDE the api container (it owns the ChromaDB volume + embedder model):
    docker cp data/rag_eval/source_docs infra-api-1:/tmp/source_docs
    docker cp backend/scripts/ingest_domain_docs.py infra-api-1:/app/scripts/
    docker exec infra-api-1 /opt/venv/bin/python -m scripts.ingest_domain_docs /tmp/source_docs
    docker restart infra-api-1   # reload chroma into the server's memory
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.rag.chunker import chunk_document
from app.rag.factory import get_embedder
from app.rag.loader import LoadedDocument, PageContent
from app.rag.store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingest_domain_docs")

# Demo migrant's company (ГК ПИК) — must match seed_demo / demo.py and the
# company_id the chat retriever filters on.
_PIK_COMPANY_ID = "11111111-1111-1111-1111-111111111111"

# Docs handled by seed_partner_products → skip them here.
_PARTNER_PREFIXES = ("partner_", "kuper_")


def _strip_frontmatter(content: str) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return content
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[i + 1:]).strip()
    return content


def main() -> None:
    docs_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/source_docs")
    if not docs_dir.exists():
        logger.error("docs dir not found: %s", docs_dir)
        sys.exit(1)

    store = VectorStore()
    embedder = get_embedder()

    total_chunks = 0
    n_docs = 0
    for path in sorted(docs_dir.glob("*.md")):
        if path.name.startswith(_PARTNER_PREFIXES):
            continue
        body = _strip_frontmatter(path.read_text(encoding="utf-8")) or path.read_text(
            encoding="utf-8"
        )
        loaded = LoadedDocument(
            file_name=path.name, pages=[PageContent(text=body, page_number=1)]
        )
        chunks = chunk_document(loaded)
        if not chunks:
            logger.warning("no chunks for %s — skipped", path.name)
            continue

        store.delete_by_file_name(path.name)  # idempotent re-ingest
        embeddings = embedder.embed_passages([c.text for c in chunks])
        store.upsert(chunks, embeddings, company_id=_PIK_COMPANY_ID, language="ru")
        total_chunks += len(chunks)
        n_docs += 1
        logger.info("%s → %d chunks", path.name, len(chunks))

    logger.info("DONE: %d domain docs, %d chunks into employer_docs_demo", n_docs, total_chunks)


if __name__ == "__main__":
    main()
