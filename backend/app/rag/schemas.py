"""Schema-Guided Reasoning (SGR) schemas for RAG answers — Phase 3.5.

GigaChat is forced to return a JSON object matching `RagAnswer`. We validate
the parsed JSON with Pydantic, which gives us:

* Anti-hallucination via `is_answerable` + `Literal["N/A"]` answer fallback.
* Chain-of-Thought as an explicit field (`reasoning`) emitted BEFORE the
  answer — this primes the model's context window (Vanguard-effect).
* Stable contract for the SSE layer — events are emitted from parsed fields,
  not from regex over freeform text.

We intentionally do NOT use GigaChat's `functions` API: it streams poorly
and adds vendor lock-in. We rely on a strict system prompt plus a reparser
retry instead — a "poor man's" structured-output pattern.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Single citation backing one statement in `RagAnswer.answer`.

    `document_title` is the human-readable title we surface to the user.
    Old code displayed the raw filename (Bug #2 from e2e 2026-05-26) —
    the citation pipeline now derives a friendly title and falls back to
    `filename without extension` if no better title is known.
    """

    document_id: str
    document_title: str = Field(
        ...,
        min_length=1,
        description="Human-readable title (NOT raw filename with .pdf).",
    )
    page_number: int = Field(
        default=0,
        description="PDF page number (0 if unknown, e.g. DOCX).",
    )
    snippet: str = Field(
        ...,
        min_length=20,
        max_length=300,
        description="Short quote from the chunk that supports the statement.",
    )


class RagAnswer(BaseModel):
    """Strict schema GigaChat must return for every RAG question.

    Order of fields matters — `reasoning` comes BEFORE `answer` so that
    the LLM writes its rationale first (Chain-of-Thought) and then composes
    the user-facing answer. This typically improves grounding by ~5-15%.
    """

    is_answerable: bool = Field(
        ...,
        description="True iff the CONTEXT contains enough info to answer.",
    )
    reasoning: str = Field(
        ...,
        min_length=30,
        max_length=400,
        description="Brief CoT explaining why the context is/isn't enough.",
    )
    answer: str = Field(
        ...,
        description=(
            "User-facing answer in Russian. MUST equal the literal string "
            "'N/A' (without quotes) when is_answerable is False."
        ),
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Empty list when is_answerable is False.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "Self-rated confidence: high = direct quote, medium = paraphrase, "
            "low = partial / inferred."
        ),
    )
