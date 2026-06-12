"""Translate golden_set.yaml questions to Hindi using OpenRouter.

One-time script. Reads data/rag_eval/golden_set.yaml (35 ru/en questions),
translates each question to Hindi (Devanagari) using Claude Sonnet via
OpenRouter, keeps expected_answer and expected_doc_id unchanged (ru-language
etalon stays in Russian for eval comparison).

Writes data/rag_eval/golden_set_hi.yaml with a warning comment that the
translations are AI-generated and require native-speaker review.

Usage:
    export OPENROUTER_API_KEY=sk-...
    python backend/scripts/translate_golden_to_hi.py

Optional env vars:
    GOLDEN_SET_INPUT  — path to input yaml (default: data/rag_eval/golden_set.yaml)
    GOLDEN_SET_HI_OUT — path to output yaml (default: data/rag_eval/golden_set_hi.yaml)
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("translate_golden_to_hi")

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent

_DEFAULT_INPUT = _REPO_ROOT / "data" / "rag_eval" / "golden_set.yaml"
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "rag_eval" / "golden_set_hi.yaml"

# Gemini вместо claude-sonnet-4: дорогая модель съедает OpenRouter-лимит (×30).
_TRANSLATE_MODEL = "google/gemini-2.5-flash"

_SYSTEM_PROMPT = (
    "Ты переводчик. Переводи предложения с русского или английского на хинди (деванагари). "
    "Сохраняй смысл полностью. Используй естественный разговорный стиль, "
    "как пишет трудовой мигрант в России. "
    "Верни ТОЛЬКО переведённое предложение — никакого объяснения, никакого обрамления."
)


def _read_env_file_key(key: str) -> str | None:
    """Try to read a key from infra/.env without importing pydantic-settings."""
    env_path = _REPO_ROOT / "infra" / ".env"
    if not env_path.exists():
        return None
    pattern = re.compile(rf"^{re.escape(key)}\s*=\s*(.+)$", re.MULTILINE)
    text = env_path.read_text(encoding="utf-8")
    m = pattern.search(text)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return None


def _get_openrouter_client() -> object:
    """Return an OpenAI-compatible client pointed at OpenRouter."""
    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ImportError:
        logger.error("openai package not installed. Run: pip install openai")
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY") or _read_env_file_key("OPENROUTER_API_KEY")
    if not api_key:
        logger.error(
            "OPENROUTER_API_KEY not found in environment or infra/.env. "
            "Export it: export OPENROUTER_API_KEY=sk-..."
        )
        sys.exit(1)

    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://adapta.demo",
            "X-Title": "AdaptaAI golden_set hi-translation",
        },
    )


def translate_question(client: object, question: str) -> str:
    """Translate a single question to Hindi via OpenRouter google/gemini-2.5-flash."""
    from openai import OpenAI  # type: ignore[import-untyped]

    assert isinstance(client, OpenAI)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=_TRANSLATE_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                temperature=0.2,
                max_tokens=512,
            )
            result = (response.choices[0].message.content or "").strip()
            if result:
                return result
            logger.warning("Empty translation for '%s', retrying...", question[:60])
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenRouter call failed (attempt %d/3): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2)
    logger.error("Translation failed after 3 attempts for: %s", question[:80])
    return question  # fallback: keep original


def main() -> None:
    input_path = Path(
        os.environ.get("GOLDEN_SET_INPUT", str(_DEFAULT_INPUT))
    )
    output_path = Path(
        os.environ.get("GOLDEN_SET_HI_OUT", str(_DEFAULT_OUTPUT))
    )

    if not input_path.exists():
        logger.error("Input golden_set.yaml not found at %s", input_path)
        sys.exit(1)

    logger.info("Reading golden set from %s", input_path)
    with input_path.open(encoding="utf-8") as f:
        golden_set: list[dict[str, str]] = yaml.safe_load(f)

    if not golden_set:
        logger.error("Empty golden set at %s", input_path)
        sys.exit(1)

    logger.info("Loaded %d questions", len(golden_set))

    client = _get_openrouter_client()

    hi_golden_set: list[dict[str, str]] = []
    for i, item in enumerate(golden_set):
        original_question = item["question"]
        logger.info("[%d/%d] Translating: %.80s", i + 1, len(golden_set), original_question)

        hi_question = translate_question(client, original_question)
        logger.info("  -> %s", hi_question[:80])

        hi_golden_set.append(
            {
                "question": hi_question,
                "expected_answer": item["expected_answer"],  # stays in Russian
                "expected_doc_id": item["expected_doc_id"],
            }
        )

        # Small delay to avoid rate-limiting
        if i < len(golden_set) - 1:
            time.sleep(0.3)

    # Write output with warning comment
    output_path.parent.mkdir(parents=True, exist_ok=True)

    comment_header = (
        "# AI-generated hi translations from golden_set.yaml. "
        "Requires native-speaker review before publishing metrics.\n"
        "# expected_answer values are kept in Russian (ru etalon for Qwen+GigaChat pipeline eval).\n"
    )

    yaml_text = yaml.dump(
        hi_golden_set,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )

    output_path.write_text(comment_header + yaml_text, encoding="utf-8")

    logger.info(
        "Done. Written %d hi-translated questions to %s",
        len(hi_golden_set),
        output_path,
    )

    # Validate: re-read and count
    with output_path.open(encoding="utf-8") as f:
        content = f.read()
    # Strip comments for yaml parsing
    yaml_only = "\n".join(
        line for line in content.splitlines() if not line.startswith("#")
    )
    reloaded: list[dict[str, str]] = yaml.safe_load(yaml_only) or []
    logger.info("Validation: %d questions in output file (expected %d)", len(reloaded), len(golden_set))

    if len(reloaded) != len(golden_set):
        logger.error(
            "Question count mismatch! Input: %d, Output: %d",
            len(golden_set),
            len(reloaded),
        )
        sys.exit(1)

    logger.info("All %d questions successfully translated and written.", len(reloaded))


if __name__ == "__main__":
    main()
