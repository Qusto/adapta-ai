"""Unit tests for _load_chunks_from_content markdown branch.

Verifies that .md / .markdown content is processed as plain text without
triggering the docx.opc PackageNotFoundError that used to occur when
non-PDF content was routed through load_docx().
"""
from __future__ import annotations

import pytest


MD_PLAIN = b"# Hello\n\nThis is a simple markdown document with enough text to chunk."

MD_WITH_FRONTMATTER = b"""---
product_id: test_product
product_title: Test Product
language: ru
---

## Main content

This is the body of the markdown document.
It has multiple lines to ensure chunks are produced.
"""


def _call(content: bytes, file_name: str, ext: str):
    """Import and call _load_chunks_from_content inside a minimal env patch."""
    import os

    # Provide just enough env to import documents module without crashing.
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-bytes-long-xxxxxxxxxxxxxx")
    os.environ.setdefault("JWT_ALGORITHM", "HS256")
    os.environ.setdefault("GIGACHAT_CLIENT_ID", "test")
    os.environ.setdefault("GIGACHAT_CLIENT_SECRET", "test")
    os.environ.setdefault("OPENROUTER_API_KEY", "test")

    from app.api.v1.documents import _load_chunks_from_content  # noqa: PLC0415

    return _load_chunks_from_content(content, file_name, ext)


class TestLoadChunksFromContentMarkdown:
    def test_plain_md_returns_nonempty_chunks(self) -> None:
        """_load_chunks_from_content with .md content returns at least one chunk."""
        chunks = _call(MD_PLAIN, "test.md", ".md")
        assert chunks, "Expected at least one chunk from .md content, got empty list"

    def test_plain_md_chunk_has_text(self) -> None:
        """Every chunk produced from .md has non-empty text."""
        chunks = _call(MD_PLAIN, "test.md", ".md")
        for chunk in chunks:
            assert isinstance(chunk.text, str)
            assert chunk.text.strip()

    def test_md_with_frontmatter_returns_nonempty_chunks(self) -> None:
        """.md with YAML frontmatter is parsed and produces chunks from the body."""
        chunks = _call(MD_WITH_FRONTMATTER, "partner_product.md", ".md")
        assert chunks, "Expected chunks from .md with frontmatter, got empty list"

    def test_md_frontmatter_not_in_chunk_text(self) -> None:
        """Frontmatter keys (product_id) must not appear in chunk text."""
        chunks = _call(MD_WITH_FRONTMATTER, "partner_product.md", ".md")
        full_text = " ".join(c.text for c in chunks)
        assert "product_id" not in full_text, (
            "Frontmatter leaked into chunk text: " + full_text[:200]
        )

    def test_markdown_ext_also_handled(self) -> None:
        """.markdown extension is treated the same as .md."""
        chunks = _call(MD_PLAIN, "readme.markdown", ".markdown")
        assert chunks, "Expected chunks for .markdown extension"
