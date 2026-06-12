"""Parse + validate GigaChat SGR responses — Phase 3.5.

GigaChat sometimes wraps JSON in ```json fences``` or adds a stray prefix.
`parse_rag_answer` is tolerant: it strips fences, finds the outermost
JSON object, and validates with Pydantic. Returns either a `RagAnswer`
or a `ParseFailure` (never raises).

The chat handler uses this twice:
  1. After the initial GigaChat stream.
  2. (Optionally) after a single reparser retry.

If both fail, we fall back to a canned `is_answerable=False` answer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.rag.schemas import RagAnswer

logger = logging.getLogger(__name__)

# ``` or ```json fences at start of buffer
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


SAFE_FALLBACK_ANSWER = RagAnswer(
    is_answerable=False,
    reasoning=(
        "Не удалось сгенерировать структурированный ответ из-за ошибки "
        "валидации LLM-вывода. Возвращаю безопасный fallback."
    ),
    answer="Не удалось сформировать ответ, попробуйте ещё раз.",
    citations=[],
    confidence="low",
)


@dataclass
class ParseFailure:
    """Returned when JSON parsing or schema validation fails."""

    error: str
    raw_text: str


def parse_rag_answer(raw_text: str) -> RagAnswer | ParseFailure:
    """Parse raw GigaChat output into a validated `RagAnswer`.

    Tolerates:
    * ```json``` fences around the object.
    * A stray prefix/suffix outside the outermost `{...}`.

    Returns `ParseFailure` (does NOT raise) so callers can decide whether
    to reparse or fall back.
    """
    if not raw_text or not raw_text.strip():
        return ParseFailure(error="empty LLM output", raw_text=raw_text)

    candidate = _strip_fences(raw_text)
    candidate = _extract_outermost_object(candidate) or candidate

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("parse_rag_answer: JSONDecodeError: %s", exc)
        return ParseFailure(error=f"JSONDecodeError: {exc}", raw_text=raw_text)

    if not isinstance(data, dict):
        return ParseFailure(
            error=f"Expected JSON object, got {type(data).__name__}",
            raw_text=raw_text,
        )

    # Normalise the N/A invariant: if is_answerable is False but answer is
    # something other than "N/A", coerce it so validation succeeds.
    if data.get("is_answerable") is False:
        if data.get("answer") != "N/A":
            data["answer"] = "N/A"
        data["citations"] = []

    try:
        return RagAnswer.model_validate(data)
    except ValidationError as exc:
        logger.warning("parse_rag_answer: ValidationError: %s", exc)
        return ParseFailure(error=f"ValidationError: {exc}", raw_text=raw_text)


def _strip_fences(text: str) -> str:
    """Drop ```json … ``` fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text)
    return text.strip()


def _extract_outermost_object(text: str) -> str | None:
    """Return the substring from the first `{` to its matching `}`.

    Walks the string with a brace-depth counter. Returns None if no
    balanced object is found.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
