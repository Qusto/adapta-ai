"""Document chunker — Phase 2 RAG ingestion §1.2.

RecursiveCharacterTextSplitter with 800-token chunks and 100-token overlap.
Preserves page number from source pages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.loader import LoadedDocument

logger = logging.getLogger(__name__)

# Target sizes in characters (approximate — embedder tokenizer counts differ,
# but character-based sizing is a pragmatic proxy for the tokenizer).
# multilingual-e5-base average ~4 chars/token → 800 tokens ≈ 3200 chars.
_CHUNK_SIZE = 3200
_CHUNK_OVERLAP = 400  # 100 tokens ≈ 400 chars


@dataclass
class Chunk:
    """A single text chunk ready for embedding."""

    text: str
    chunk_idx: int
    page: int | None  # 1-based PDF page; None for DOCX
    file_name: str


def chunk_document(doc: LoadedDocument) -> list[Chunk]:
    """Split a LoadedDocument into overlapping text chunks.

    Strategy: RecursiveCharacterTextSplitter with separators
    ["\n\n", "\n", ". ", " ", ""] per PRD §1.2. One splitter instance
    processes all pages and chunks are numbered globally.

    Args:
        doc: Parsed document from loader.load_pdf / loader.load_docx.

    Returns:
        List of Chunk objects with sequential chunk_idx starting at 0.
    """
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " ", ""],
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        length_function=len,
        is_separator_regex=False,
    )

    chunks: list[Chunk] = []
    global_idx = 0

    for page in doc.pages:
        text = page.text.strip()
        if not text:
            continue

        splits = splitter.split_text(text)
        for split_text in splits:
            stripped = split_text.strip()
            if not stripped:
                continue
            chunks.append(
                Chunk(
                    text=stripped,
                    chunk_idx=global_idx,
                    page=page.page_number,  # None for DOCX
                    file_name=doc.file_name,
                )
            )
            global_idx += 1

    logger.info("Chunked document %s into %d chunks", doc.file_name, len(chunks))
    return chunks
