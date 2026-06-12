"""RAG evaluation pipeline for AdaptaAI.

Usage:
    python eval_rag.py build-set
    python eval_rag.py run --golden-set data/rag_eval/golden_set.yaml \\
                           --prod-url http://localhost:8080 \\
                           --demo-password <ADAPTA_DEMO_PASSWORD>
    python eval_rag.py report --run-dir data/rag_eval/runs/<timestamp>

Runs outside Docker in a dedicated venv (data/rag_eval/.venv).
Judge LLM: OpenRouter google/gemini-2.5-flash (cheap; set via RAGAS_JUDGE_MODEL in infra/.env).
  NB: НЕ использовать claude-sonnet-4 как судью — дорого (×30), съедает OpenRouter-лимит.
Embeddings: paraphrase-multilingual-mpnet-base-v2 (HuggingFace, local).

Extended metrics (added 2026-05-28):
  - latency_ms per question (wall-time from POST to SSE close)
  - tokens_in / tokens_out per question (from SSE meta event or tiktoken approx)
  - cost_total_usd (GigaChat-Pro: $0.002/1k tokens)
  - ROUGE-L recall and BLEU-4 (via rouge_score + sacrebleu/nltk)
  - retrieval hit@3 and MRR
  - NoiseSensitivity (ragas 0.2 if available)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval_rag")

# ---------------------------------------------------------------------------
# Repo-root detection (works from any cwd)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
_SOURCE_DOCS = _REPO_ROOT / "data" / "rag_eval" / "source_docs"
_GOLDEN_SET_DEFAULT = _REPO_ROOT / "data" / "rag_eval" / "golden_set.yaml"
_RUNS_DIR = _REPO_ROOT / "data" / "rag_eval" / "runs"

# Pricing constants.
# Exchange rate: approximate, for reporting only.
_RUB_PER_USD = 90.0  # оценка, фиксируется для воспроизводимости

# Per-generator pricing: (prompt_cost_per_1k_usd, completion_cost_per_1k_usd)
# GigaChat-2-Pro: 0.5 ₽/1k tokens (одинаково для prompt и completion)
_PRICING: dict[str, tuple[float, float]] = {
    "gigachat": (0.5 / _RUB_PER_USD, 0.5 / _RUB_PER_USD),  # 0.5 ₽/1k токенов (физики), ≈$0.00556/1k
    # Qwen 2.5 72B instruct
    "qwen-2.5-72b": (0.12 / 1000, 0.39 / 1000),
    # Qwen3 235B A22B
    "qwen3-235b": (0.455 / 1000, 1.82 / 1000),
    # Qwen3 Max / Qwen-Max
    "qwen3-max": (0.78 / 1000, 3.90 / 1000),
}
# For backward compat / fallback
_GIGACHAT_PRO_COST_PER_1K_USD = _PRICING["gigachat"][0]


def _get_pricing(generator: str) -> tuple[float, float]:
    """Return (prompt_usd_per_1k, completion_usd_per_1k) for given generator string.

    Matching rules (case-insensitive substring):
    - 'gigachat'      → GigaChat-2-Pro (0.5 ₽/1k both directions)
    - 'qwen-2.5-72b'  → Qwen 2.5 72B
    - 'qwen3-235b'    → Qwen3 235B A22B
    - 'qwen3-max' or 'qwen-max' → Qwen3 Max
    - unknown         → GigaChat-2-Pro (с fallback-пометкой в логах)
    """
    g = (generator or "").lower()
    if "gigachat" in g:
        return _PRICING["gigachat"]
    if "qwen-2.5-72b" in g or "qwen2.5-72b" in g:
        return _PRICING["qwen-2.5-72b"]
    if "qwen3-235b" in g:
        return _PRICING["qwen3-235b"]
    if "qwen3-max" in g or "qwen-max" in g:
        return _PRICING["qwen3-max"]
    # Unknown generator — fallback to GigaChat pricing
    logger.warning("Unknown generator %r — falling back to GigaChat-2-Pro pricing", generator)
    return _PRICING["gigachat"]

# ---------------------------------------------------------------------------
# build_golden_set
# ---------------------------------------------------------------------------

_SYSTEM_GENERATE_QA = textwrap.dedent(
    """\
    Ты генератор вопросов для оценки RAG-системы.
    Пользователь даст тебе markdown-документ о продукте Сбербанка для мигрантов.
    Сгенерируй {n} вопросов и ответов на основе ТОЛЬКО этого документа.
    Включи вопросы на русском и английском языках (хотя бы один вопрос на каждом языке).
    Каждый вопрос должен требовать конкретного факта из документа.

    Ответ СТРОГО в формате JSON-массива:
    [
      {{"question": "...", "expected_answer": "..."}},
      ...
    ]
    Никакого другого текста, только JSON.
    """
)


def _load_openrouter_client() -> Any:
    """Return an OpenAI-compatible client pointed at OpenRouter."""
    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ImportError:
        logger.error("openai package not installed. Run: pip install langchain-openai")
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY") or _read_env_file_key("OPENROUTER_API_KEY")
    if not api_key:
        logger.error(
            "OPENROUTER_API_KEY not found in environment or infra/.env. "
            "Export it before running: export OPENROUTER_API_KEY=sk-..."
        )
        sys.exit(1)

    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://adapta.demo",
            "X-Title": "AdaptaAI RAG Eval",
        },
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


def _choose_judge_model(client: Any) -> str:
    """Pick best available judge model on OpenRouter.

    Default — cheap-and-fast (gemini-flash, gpt-4o-mini). Claude был дорогой —
    его одиночный прогон 35 Q×6 metrics × ~2k tokens судебных промптов съел
    почти весь OpenRouter-лимит. Дешёвые модели за пределами 30× по цене
    показывают сравнимое качество для evaluation tasks.
    Override через env: RAGAS_JUDGE_MODEL=google/gemini-2.0-flash-001
    """
    env_override = os.environ.get("RAGAS_JUDGE_MODEL") or _read_env_file_key("RAGAS_JUDGE_MODEL")
    if env_override:
        return env_override

    preferred = [
        "google/gemini-2.5-flash",        # $0.10 / $0.50 — primary: best ru/hi judge среди дешёвых
        "google/gemini-2.0-flash-001",   # $0.075 / $0.30 — cheaper fallback
        "openai/gpt-oss-120b",            # $0.10 / $0.30 — open-weights fallback (Groq inference)
        "openai/gpt-4o-mini",             # $0.15 / $0.60 — proven baseline
    ]
    for model in preferred:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            if resp.choices:
                logger.info("Judge model selected: %s", model)
                return model
        except Exception as exc:  # noqa: BLE001
            logger.debug("Model %s not available: %s", model, exc)
    logger.warning("No preferred model available, falling back to first in list")
    return preferred[0]


def build_golden_set(
    source_docs: Path = _SOURCE_DOCS,
    output: Path = _GOLDEN_SET_DEFAULT,
    questions_per_doc: int = 5,
    force: bool = False,
) -> None:
    """Read source_docs/*.md, generate Q&A pairs via OpenRouter, write golden_set.yaml."""
    if output.exists() and not force:
        logger.info("golden_set.yaml already exists at %s. Use --force to regenerate.", output)
        return

    md_files = sorted(source_docs.glob("*.md"))
    if not md_files:
        logger.error("No .md files found in %s", source_docs)
        sys.exit(1)

    logger.info("Found %d source docs: %s", len(md_files), [f.name for f in md_files])
    client = _load_openrouter_client()
    judge_model = _choose_judge_model(client)

    golden_set: list[dict[str, str]] = []

    for md_file in md_files:
        doc_id = md_file.stem
        content = md_file.read_text(encoding="utf-8")
        logger.info("Generating %d Q&A pairs for doc: %s", questions_per_doc, doc_id)

        system_prompt = _SYSTEM_GENERATE_QA.format(n=questions_per_doc)
        try:
            response = client.chat.completions.create(
                model=judge_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
            raw = response.choices[0].message.content or "[]"
        except Exception as exc:  # noqa: BLE001
            logger.error("OpenRouter call failed for %s: %s", doc_id, exc)
            continue

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())

        try:
            pairs: list[dict[str, str]] = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error for %s: %s\nRaw: %.200s", doc_id, exc, raw)
            continue

        for pair in pairs:
            if "question" in pair and "expected_answer" in pair:
                golden_set.append(
                    {
                        "question": str(pair["question"]),
                        "expected_answer": str(pair["expected_answer"]),
                        "expected_doc_id": doc_id,
                    }
                )

    if not golden_set:
        logger.error("No Q&A pairs generated. Check OpenRouter key and source docs.")
        sys.exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        yaml.dump(
            golden_set,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    logger.info("Golden set written: %d pairs -> %s", len(golden_set), output)


# ---------------------------------------------------------------------------
# run_eval
# ---------------------------------------------------------------------------


def _get_jwt_token(prod_url: str, demo_password: str) -> str:
    """Obtain JWT via demo migrant login endpoint (Раджу Шарма)."""
    demo_url = f"{prod_url.rstrip('/')}/api/v1/demo/login-migrant"
    try:
        resp = httpx.post(
            demo_url,
            headers={"X-Demo-Password": demo_password},
            timeout=30,
        )
        resp.raise_for_status()
        token: str = resp.json()["access_token"]
        logger.info("JWT obtained from demo endpoint %s", demo_url)
        return token
    except Exception as exc:  # noqa: BLE001
        logger.warning("Demo login failed: %s. Trying HR login...", exc)
        # Fallback: try HR user login
        try:
            hr_url = f"{prod_url.rstrip('/')}/api/v1/auth/login"
            resp2 = httpx.post(
                hr_url,
                json={"email": "hr@demo.local", "password": demo_password},
                timeout=30,
            )
            resp2.raise_for_status()
            token2: str = resp2.json()["access_token"]
            logger.info("JWT obtained from HR endpoint %s", hr_url)
            return token2
        except Exception as exc2:  # noqa: BLE001
            logger.error("All JWT endpoints failed: %s", exc2)
            sys.exit(1)


def _approx_tokens_tiktoken(text: str) -> int:
    """Approximate token count using tiktoken (cl100k_base). Falls back to word count."""
    try:
        import tiktoken  # type: ignore[import-untyped]
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001
        # Rough approximation: ~1.3 tokens per word for Russian text
        return int(len(text.split()) * 1.3)


def _parse_sse_events(raw_text: str) -> list[tuple[str, str]]:
    """Parse raw SSE text into list of (event_name, data_str) tuples."""
    events: list[tuple[str, str]] = []
    current_event = ""
    for line in raw_text.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:") and current_event:
            data_str = line[len("data:"):].strip()
            events.append((current_event, data_str))
            current_event = ""
    return events


def _parse_sse_response(
    raw_text: str,
) -> tuple[str, list[str], int, int, str]:
    """Parse SSE response from /api/v1/chat/messages.

    Returns (answer_text, list_of_citation_strings, tokens_in, tokens_out, generator).
    SSE events: message_started, token (N x), answer, citations, meta, done.

    Priority order for token counts:
    1. 'done' event fields: prompt_tokens, completion_tokens (реальные токены).
    2. 'meta' event fields: tokens_in / tokens_out (legacy).
    3. tiktoken approximation from answer/context text.

    generator comes from the 'done' event field 'generator' (e.g. "gigachat", "qwen/...").
    """
    answer = ""
    citations: list[str] = []
    tokens_in_meta = 0
    tokens_out_meta = 0
    tokens_in_done = 0
    tokens_out_done = 0
    generator = ""

    for event_name, data_str in _parse_sse_events(raw_text):
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        if event_name == "answer":
            answer = data.get("text", "")
        elif event_name == "citations":
            raw_citations = data.get("citations", [])
            for c in raw_citations:
                if isinstance(c, dict):
                    # Citation may have content, chunk_text, text, doc_id, etc.
                    text = (
                        c.get("chunk_text")
                        or c.get("content")
                        or c.get("text")
                        or str(c)
                    )
                    citations.append(text)
                elif isinstance(c, str):
                    citations.append(c)
        elif event_name == "meta":
            # Non-trace meta events carry token counts (legacy fallback)
            if "trace" not in data:
                tokens_in_meta = int(data.get("tokens_in", 0))
                tokens_out_meta = int(data.get("tokens_out", 0))
        elif event_name == "done":
            # 'done' carries real token counts and generator name — highest priority
            pt = data.get("prompt_tokens", 0)
            ct = data.get("completion_tokens", 0)
            if pt:
                tokens_in_done = int(pt)
            if ct:
                tokens_out_done = int(ct)
            if data.get("generator"):
                generator = str(data["generator"])

    # Priority: done > meta > tiktoken approximation
    tokens_in = tokens_in_done or tokens_in_meta
    tokens_out = tokens_out_done or tokens_out_meta

    # Fallback: approximate tokens if not provided by API
    if tokens_out == 0 and answer:
        tokens_out = _approx_tokens_tiktoken(answer)
    if tokens_in == 0 and citations:
        # Approximate prompt as context chunks + question
        context_text = " ".join(citations)
        tokens_in = _approx_tokens_tiktoken(context_text)

    return answer, citations, tokens_in, tokens_out, generator


def _parse_sse_response_with_trace(
    raw_text: str,
) -> tuple[str, list[str], int, int, dict[str, Any]]:
    """Parse SSE response with trace=True, extracting intermediate pipeline data.

    Returns (answer_text, citations, tokens_in, tokens_out, trace_data).
    trace_data keys: step_a_qwen_ru_question, retrieved_doc_ids, retrieved_chunks,
                     gigachat_ru_answer, step_b_qwen_hi_answer
    """
    answer = ""
    citations: list[str] = []
    tokens_in = 0
    tokens_out = 0
    trace_data: dict[str, Any] = {}

    for event_name, data_str in _parse_sse_events(raw_text):
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        if event_name == "answer":
            answer = data.get("text", "")
        elif event_name == "citations":
            raw_citations = data.get("citations", [])
            for c in raw_citations:
                if isinstance(c, dict):
                    text = (
                        c.get("chunk_text")
                        or c.get("content")
                        or c.get("text")
                        or str(c)
                    )
                    citations.append(text)
                elif isinstance(c, str):
                    citations.append(c)
        elif event_name == "meta":
            if "trace" in data:
                # Merge all trace sub-dicts from multiple meta events
                trace_data.update(data["trace"])
            else:
                tokens_in = int(data.get("tokens_in", 0))
                tokens_out = int(data.get("tokens_out", 0))

    # Fallback: approximate tokens if not provided by API
    if tokens_out == 0 and answer:
        tokens_out = _approx_tokens_tiktoken(answer)
    if tokens_in == 0 and citations:
        context_text = " ".join(citations)
        tokens_in = _approx_tokens_tiktoken(context_text)

    return answer, citations, tokens_in, tokens_out, trace_data


def _extract_doc_id_from_context(context: str) -> str | None:
    """Try to extract document_id or document_name from a context chunk string."""
    # Contexts arrive as stringified dicts like:
    # "{'document_id': 'kuper_migrant.md', 'document_name': '...', ...}"
    # or as plain text strings.
    patterns = [
        r"'document_id'\s*:\s*'([^']+)'",
        r'"document_id"\s*:\s*"([^"]+)"',
        r"'document_name'\s*:\s*'([^']+)'",
        r'"document_name"\s*:\s*"([^"]+)"',
        r"source['\"]?\s*:\s*['\"]([^'\"]+)['\"]",
    ]
    for pat in patterns:
        m = re.search(pat, context)
        if m:
            val = m.group(1)
            # Normalize: strip .md suffix to match expected_doc_id format
            return val.replace(".md", "").strip()
    return None


def _compute_retrieval_metrics(
    eval_results: list[dict[str, Any]],
    k: int = 3,
) -> dict[str, float]:
    """Compute hit@k and MRR from eval results.

    Uses expected_doc_id vs. document IDs parsed from contexts.
    """
    hits = 0
    reciprocal_ranks: list[float] = []

    for row in eval_results:
        expected = row.get("expected_doc_id", "")
        contexts = row.get("contexts", [])
        if not expected or not contexts:
            reciprocal_ranks.append(0.0)
            continue

        found_rank = None
        for rank, ctx in enumerate(contexts[:k], start=1):
            doc_id = _extract_doc_id_from_context(str(ctx))
            if doc_id and (
                doc_id == expected
                or doc_id.startswith(expected)
                or expected.startswith(doc_id)
            ):
                found_rank = rank
                break

        if found_rank is not None:
            hits += 1
            reciprocal_ranks.append(1.0 / found_rank)
        else:
            reciprocal_ranks.append(0.0)

    n = len(eval_results)
    hit_at_k = hits / n if n > 0 else 0.0
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0

    return {
        f"retrieval_hit_at_{k}": round(hit_at_k, 4),
        "retrieval_mrr": round(mrr, 4),
    }


def _compute_nlg_metrics(
    eval_results: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute ROUGE-L recall and BLEU-4.

    Requires rouge_score and either sacrebleu or nltk.
    Returns empty dict (with warnings) if packages are missing.
    """
    metrics: dict[str, float] = {}

    # --- ROUGE-L ---
    try:
        from rouge_score import rouge_scorer  # type: ignore[import-untyped]

        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)
        rouge_scores: list[float] = []
        for row in eval_results:
            hyp = row.get("answer", "")
            ref = row.get("expected_answer", "")
            if hyp and ref:
                score = scorer.score(ref, hyp)
                rouge_scores.append(score["rougeL"].recall)
        if rouge_scores:
            metrics["rouge_l_recall"] = round(sum(rouge_scores) / len(rouge_scores), 4)
            logger.info("ROUGE-L recall: %.4f (n=%d)", metrics["rouge_l_recall"], len(rouge_scores))
    except ImportError:
        logger.warning(
            "rouge_score not installed — skipping ROUGE-L. "
            "Add rouge_score to requirements.txt and run: pip install rouge_score"
        )

    # --- BLEU-4 ---
    try:
        import sacrebleu  # type: ignore[import-untyped]

        hypotheses = [row.get("answer", "") for row in eval_results]
        references = [[row.get("expected_answer", "") for row in eval_results]]
        bleu = sacrebleu.corpus_bleu(hypotheses, references)
        metrics["bleu_4"] = round(bleu.score / 100.0, 4)  # sacrebleu returns 0-100
        logger.info("BLEU-4: %.4f", metrics["bleu_4"])
    except ImportError:
        # Try nltk fallback
        try:
            from nltk.translate.bleu_score import (  # type: ignore[import-untyped]
                corpus_bleu,
                SmoothingFunction,
            )

            smoothie = SmoothingFunction().method1
            list_of_references = [
                [row.get("expected_answer", "").split()] for row in eval_results
            ]
            hypotheses_tok = [row.get("answer", "").split() for row in eval_results]
            bleu_score = corpus_bleu(
                list_of_references,
                hypotheses_tok,
                smoothing_function=smoothie,
            )
            metrics["bleu_4"] = round(float(bleu_score), 4)
            logger.info("BLEU-4 (nltk): %.4f", metrics["bleu_4"])
        except ImportError:
            logger.warning(
                "Neither sacrebleu nor nltk installed — skipping BLEU-4. "
                "Add sacrebleu to requirements.txt."
            )

    return metrics


def _compute_cost(eval_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute estimated cost in USD and RUB from tokens_in/tokens_out/generator per result.

    Uses per-generator pricing (_get_pricing). If multiple generators appear in results,
    each result is priced individually. Returns cost in both USD and RUB, plus token totals
    and the set of observed generators.
    """
    cost_usd = 0.0
    total_in = 0
    total_out = 0
    generators_seen: set[str] = set()

    for r in eval_results:
        tok_in = int(r.get("tokens_in", 0))
        tok_out = int(r.get("tokens_out", 0))
        gen = r.get("generator", "") or ""
        prompt_per_1k, completion_per_1k = _get_pricing(gen)
        cost_usd += tok_in / 1000.0 * prompt_per_1k
        cost_usd += tok_out / 1000.0 * completion_per_1k
        total_in += tok_in
        total_out += tok_out
        generators_seen.add(gen if gen else "unknown")

    cost_rub = cost_usd * _RUB_PER_USD
    generators_str = ", ".join(sorted(generators_seen)) if generators_seen else "unknown"

    return {
        "cost_total_usd": round(cost_usd, 6),
        "cost_total_rub": round(cost_rub, 4),
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "generators": generators_str,
    }


def _compute_latency_stats(eval_results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute p50, p95, mean latency from per-question latency_ms."""
    latencies = [r["latency_ms"] for r in eval_results if r.get("latency_ms") is not None]
    if not latencies:
        return {}
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    p50 = sorted_lat[int(n * 0.50)]
    p95 = sorted_lat[min(int(n * 0.95), n - 1)]
    mean_lat = sum(sorted_lat) / n
    return {
        "latency_p50_ms": round(p50, 1),
        "latency_p95_ms": round(p95, 1),
        "latency_mean_ms": round(mean_lat, 1),
    }


_CHAT_TIMEOUT_S = float(os.getenv("EVAL_CHAT_TIMEOUT_S", "60"))  # GigaChat SGR can take up to 50s
_RETRY_MAX = int(os.getenv("EVAL_RETRY_MAX", "3"))
_RETRY_BASE_PAUSE_S = float(os.getenv("EVAL_RETRY_BASE_PAUSE_S", "2"))
# Inter-request pause — override через env. Default 1.5s (≈40 req/min).
# Если GigaChat валит на burst — поставь EVAL_INTER_REQUEST_PAUSE_S=30 (≈2 req/min).
_INTER_REQUEST_PAUSE_S = float(os.getenv("EVAL_INTER_REQUEST_PAUSE_S", "1.5"))
_TIMEOUT_SENTINEL = "__TIMEOUT__"


def _post_with_retry(
    http_client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    q_num: int,
    q_total: int,
) -> tuple[str, float | None]:
    """POST to chat API with retry on network/timeout errors.

    Returns (raw_sse_text, latency_ms).
    On persistent timeout after _RETRY_MAX attempts, returns (__TIMEOUT__, latency_ms).
    Never retries on 4xx responses (auth/validation errors).
    """
    raw_sse = ""
    latency_ms: float | None = None

    for attempt in range(1, _RETRY_MAX + 1):
        if attempt > 1:
            pause = _RETRY_BASE_PAUSE_S * (2 ** (attempt - 2))  # 2, 4, 8 ...
            print(
                f"Q {q_num}/{q_total} — retrying ({attempt}/{_RETRY_MAX}) "
                f"after timeout, pause {pause:.0f}s",
                flush=True,
            )
            time.sleep(pause)

        try:
            t_start = time.monotonic()
            resp = http_client.post(url, json=payload, headers=headers)
            t_end = time.monotonic()
            latency_ms = round((t_end - t_start) * 1000, 1)

            if resp.status_code >= 400:
                logger.warning(
                    "Q %d/%d — HTTP %d, not retrying: %s",
                    q_num, q_total, resp.status_code, resp.text[:200],
                )
                return "", latency_ms

            resp.raise_for_status()
            raw_sse = resp.text
            logger.info("Q %d/%d — OK, latency=%.0f ms", q_num, q_total, latency_ms or 0)
            return raw_sse, latency_ms

        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout) as exc:
            latency_ms = round((time.monotonic() - t_start) * 1000, 1)
            logger.warning(
                "Q %d/%d attempt %d/%d — timeout/network: %s",
                q_num, q_total, attempt, _RETRY_MAX, exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Q %d/%d attempt %d/%d — error: %s", q_num, q_total, attempt, _RETRY_MAX, exc)
            break  # Non-network error — don't retry

    # All retries exhausted
    logger.error("Q %d/%d — all %d retries failed, recording as TIMEOUT", q_num, q_total, _RETRY_MAX)
    return _TIMEOUT_SENTINEL, latency_ms


def run_eval(
    golden_set_path: Path,
    prod_url: str,
    demo_password: str | None = None,
    jwt_token: str | None = None,
    lang: str = "ru",
    pipeline_mode: str | None = None,
    qwen_model: str | None = None,
) -> list[dict[str, Any]]:
    """Run golden set against prod API, collect answers + retrieved chunks + latency.

    lang: "ru" (default) or "hi". When "hi", sends skip_translate_response=True
    so the answer stays in Russian for comparison against ru etalons.
    Uses 60s timeout, 3-attempt retry with exponential backoff, 1.5s inter-request pause.
    """
    if not golden_set_path.exists():
        logger.error("golden_set.yaml not found at %s", golden_set_path)
        sys.exit(1)

    with golden_set_path.open(encoding="utf-8") as f:
        golden_set: list[dict[str, str]] = yaml.safe_load(f)

    if not golden_set:
        logger.error("Empty golden set at %s", golden_set_path)
        sys.exit(1)

    if jwt_token is None:
        if demo_password is None:
            logger.error("Provide either --jwt-token or --demo-password to authenticate")
            sys.exit(1)
        jwt_token = _get_jwt_token(prod_url, demo_password)

    chat_url = f"{prod_url.rstrip('/')}/api/v1/chat/messages"
    results: list[dict[str, Any]] = []
    n_total = len(golden_set)

    logger.info("Running eval with lang=%s, %d questions", lang, n_total)

    with httpx.Client(timeout=_CHAT_TIMEOUT_S) as http_client:
        for i, item in enumerate(golden_set):
            question = item["question"]
            q_num = i + 1
            print(f"Q {q_num}/{n_total}: {question[:70]}", flush=True)

            # Build request payload depending on lang
            if lang == "hi":
                # hi-path: send question in Hindi, skip Step B so answer stays in Russian
                request_payload: dict[str, Any] = {
                    "text": question,
                    "language": "hi",
                    "skip_translate_response": True,
                }
            else:
                request_payload = {"text": question, "language": "ru"}
            # Ablation overrides: inject only when provided
            if pipeline_mode:
                request_payload["pipeline_mode"] = pipeline_mode
            if qwen_model:
                request_payload["qwen_model_override"] = qwen_model

            raw_sse, latency_ms = _post_with_retry(
                http_client=http_client,
                url=chat_url,
                payload=request_payload,
                headers={"Authorization": f"Bearer {jwt_token}"},
                q_num=q_num,
                q_total=n_total,
            )

            if raw_sse and raw_sse != _TIMEOUT_SENTINEL:
                answer, contexts, tokens_in, tokens_out, generator = _parse_sse_response(raw_sse)
            elif raw_sse == _TIMEOUT_SENTINEL:
                answer, contexts, tokens_in, tokens_out, generator = _TIMEOUT_SENTINEL, [], 0, 0, ""
            else:
                answer, contexts, tokens_in, tokens_out, generator = "", [], 0, 0, ""

            results.append(
                {
                    "question": question,
                    "expected_answer": item.get("expected_answer", ""),
                    "expected_doc_id": item.get("expected_doc_id", ""),
                    "answer": answer,
                    "contexts": contexts,
                    "latency_ms": latency_ms,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "generator": generator,
                    "raw_response": raw_sse[:500] if raw_sse and raw_sse != _TIMEOUT_SENTINEL else "",
                }
            )

            # Inter-request pause to avoid GigaChat rate limiting
            if i < n_total - 1:
                time.sleep(_INTER_REQUEST_PAUSE_S)

    n_timeout = sum(1 for r in results if r.get("answer") == _TIMEOUT_SENTINEL)
    logger.info(
        "Eval run complete: %d questions processed, %d timeouts",
        len(results), n_timeout,
    )
    return results


# ---------------------------------------------------------------------------
# Per-step evaluation helpers
# ---------------------------------------------------------------------------


def back_translate_hi_to_ru(hi_text: str) -> str:
    """Back-translate Hindi text to Russian via OpenRouter Qwen for round-trip eval.

    Used in per-step Step B measurement: translate Qwen hi-answer back to RU,
    then compare with the original GigaChat RU answer.
    Falls back to empty string on any error.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY") or _read_env_file_key("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — skipping back-translation")
        return ""

    try:
        import httpx as _httpx  # already imported at module level but be explicit

        payload = {
            "model": "qwen/qwen-2.5-72b-instruct",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a translator. Translate the following Hindi text to Russian. "
                        "Output ONLY the Russian translation, nothing else."
                    ),
                },
                {"role": "user", "content": hi_text},
            ],
            "max_tokens": 1024,
            "temperature": 0,
        }
        resp = _httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://adapta.demo",
                "X-Title": "AdaptaAI RAG Eval back-translate",
            },
            timeout=30,
        )
        resp.raise_for_status()
        content: str = resp.json()["choices"][0]["message"]["content"]
        return content.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("back_translate_hi_to_ru failed: %s", exc)
        return ""


def run_eval_perstep(
    golden_set_hi_path: Path,
    golden_set_ru_path: Path,
    prod_url: str,
    demo_password: str | None = None,
    jwt_token: str | None = None,
) -> list[dict[str, Any]]:
    """Run per-step hi-pipeline eval with trace=True.

    For each question:
      1. POST {text: hi_q, lang: hi, trace: true} to get full pipeline + trace data
      2. Call back_translate_hi_to_ru(qwen_hi_answer) for Step B round-trip

    Returns list of rows with per-step data for per-step metrics computation.
    Uses 60s timeout, 3-attempt retry, 1.5s inter-request pause.
    """
    if not golden_set_hi_path.exists():
        logger.error("golden_set_hi.yaml not found at %s", golden_set_hi_path)
        sys.exit(1)
    if not golden_set_ru_path.exists():
        logger.error("golden_set.yaml not found at %s", golden_set_ru_path)
        sys.exit(1)

    with golden_set_hi_path.open(encoding="utf-8") as f:
        golden_hi: list[dict[str, str]] = yaml.safe_load(f)
    with golden_set_ru_path.open(encoding="utf-8") as f:
        golden_ru: list[dict[str, str]] = yaml.safe_load(f)

    if not golden_hi or not golden_ru:
        logger.error("Empty golden set")
        sys.exit(1)

    if jwt_token is None:
        if demo_password is None:
            logger.error("Provide either --jwt-token or --demo-password")
            sys.exit(1)
        jwt_token = _get_jwt_token(prod_url, demo_password)

    chat_url = f"{prod_url.rstrip('/')}/api/v1/chat/messages"
    results: list[dict[str, Any]] = []
    n_total = len(golden_hi)

    logger.info("Per-step eval: %d hi-questions with trace=True", n_total)

    with httpx.Client(timeout=_CHAT_TIMEOUT_S) as http_client:
        for i, hi_item in enumerate(golden_hi):
            ru_item = golden_ru[i] if i < len(golden_ru) else {}
            hi_question = hi_item["question"]
            q_num = i + 1

            print(f"Q {q_num}/{n_total} [perstep]: {hi_question[:60]}", flush=True)

            request_payload: dict[str, Any] = {
                "text": hi_question,
                "language": "hi",
                "trace": True,
                # Do NOT skip_translate_response — we want the full pipeline including Step B
            }

            raw_sse, latency_ms = _post_with_retry(
                http_client=http_client,
                url=chat_url,
                payload=request_payload,
                headers={"Authorization": f"Bearer {jwt_token}"},
                q_num=q_num,
                q_total=n_total,
            )

            if raw_sse and raw_sse != _TIMEOUT_SENTINEL:
                answer, contexts, tokens_in, tokens_out, trace_data = (
                    _parse_sse_response_with_trace(raw_sse)
                )
            elif raw_sse == _TIMEOUT_SENTINEL:
                answer = _TIMEOUT_SENTINEL
                contexts, tokens_in, tokens_out = [], 0, 0
                trace_data = {}
            else:
                answer, contexts, tokens_in, tokens_out, trace_data = "", [], 0, 0, {}

            # Step B round-trip: back-translate hi-answer to RU for comparison
            qwen_hi_answer = trace_data.get("step_b_qwen_hi_answer", answer if answer != _TIMEOUT_SENTINEL else "")
            qwen_back_ru_answer = ""
            if qwen_hi_answer and answer != _TIMEOUT_SENTINEL:
                print(f"  → back-translating Step B answer...", flush=True)
                qwen_back_ru_answer = back_translate_hi_to_ru(qwen_hi_answer)

            row: dict[str, Any] = {
                "hi_question": hi_question,
                "ru_question_expected": ru_item.get("question", ""),
                "expected_doc_id": hi_item.get("expected_doc_id", ru_item.get("expected_doc_id", "")),
                "ru_expected_answer": hi_item.get("expected_answer", ru_item.get("expected_answer", "")),
                # Step A
                "qwen_ru_question": trace_data.get("step_a_qwen_ru_question", ""),
                # Retrieval
                "retrieved_doc_ids": trace_data.get("retrieved_doc_ids", []),
                "retrieved_chunks": trace_data.get("retrieved_chunks", []),
                # Generation
                "gigachat_ru_answer": trace_data.get("gigachat_ru_answer", ""),
                # Step B
                "qwen_hi_answer": qwen_hi_answer,
                "qwen_back_ru_answer": qwen_back_ru_answer,
                # Final answer (hi if Step B ran, ru if skipped)
                "final_answer": answer,
                "contexts": contexts,
                "latency_ms": latency_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "is_timeout": answer == _TIMEOUT_SENTINEL,
            }
            results.append(row)

            if i < n_total - 1:
                time.sleep(_INTER_REQUEST_PAUSE_S)

    n_timeout = sum(1 for r in results if r.get("is_timeout"))
    logger.info(
        "Per-step eval complete: %d questions, %d timeouts",
        len(results), n_timeout,
    )
    return results


def compute_perstep_metrics(
    perstep_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute per-step metrics from run_eval_perstep results.

    Returns structured dict with step_a, retrieval, generation, step_b, e2e sections.
    Uses sacrebleu for chrF/BLEU-4 and sentence-transformers for cosine.
    Ragas for context_precision, context_recall, faithfulness, answer_correctness, etc.
    """
    import numpy as np  # type: ignore[import-untyped]

    metrics: dict[str, Any] = {}
    n_total = len(perstep_results)
    n_timeout = sum(1 for r in perstep_results if r.get("is_timeout"))
    metrics["questions"] = n_total
    metrics["questions_timeout"] = n_timeout

    valid_rows = [r for r in perstep_results if not r.get("is_timeout")]
    logger.info("Computing per-step metrics on %d valid rows (of %d total)", len(valid_rows), n_total)

    # -------------------------------------------------------------------------
    # Step A: chrF, BLEU-4, cosine between qwen_ru_question and ru_question_expected
    # -------------------------------------------------------------------------
    step_a_rows = [
        r for r in valid_rows
        if r.get("qwen_ru_question") and r.get("ru_question_expected")
    ]
    step_a: dict[str, float] = {}

    if step_a_rows:
        try:
            import sacrebleu  # type: ignore[import-untyped]

            hyps = [r["qwen_ru_question"] for r in step_a_rows]
            refs = [[r["ru_question_expected"] for r in step_a_rows]]
            chrf_result = sacrebleu.corpus_chrf(hyps, refs)
            step_a["chrf"] = round(float(chrf_result.score) / 100.0, 4)
            bleu_result = sacrebleu.corpus_bleu(hyps, refs)
            step_a["bleu"] = round(float(bleu_result.score) / 100.0, 4)
            logger.info("Step A chrF=%.4f, BLEU=%.4f", step_a["chrf"], step_a["bleu"])
        except ImportError:
            logger.warning("sacrebleu not installed — skipping Step A chrF/BLEU")

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            emb_model = SentenceTransformer(
                os.environ.get(
                    "RAGAS_EMBEDDING_MODEL",
                    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                )
            )
            hyp_embs = emb_model.encode([r["qwen_ru_question"] for r in step_a_rows], normalize_embeddings=True)
            ref_embs = emb_model.encode([r["ru_question_expected"] for r in step_a_rows], normalize_embeddings=True)
            cosines = [float(np.dot(h, r)) for h, r in zip(hyp_embs, ref_embs)]
            step_a["cosine"] = round(sum(cosines) / len(cosines), 4)
            logger.info("Step A cosine=%.4f", step_a["cosine"])
        except ImportError:
            logger.warning("sentence_transformers not installed — skipping Step A cosine")

    metrics["step_a"] = step_a

    # -------------------------------------------------------------------------
    # Retrieval: hit@1, hit@3, hit@5, MRR
    # -------------------------------------------------------------------------
    retrieval: dict[str, Any] = {}

    def _check_hit(retrieved_ids: list[str], expected: str, top_k: int) -> tuple[bool, float]:
        """Return (hit, reciprocal_rank) for top-k retrieved IDs."""
        for rank, doc_id in enumerate(retrieved_ids[:top_k], start=1):
            normalized = doc_id.replace(".md", "").strip()
            if normalized == expected or normalized.startswith(expected) or expected.startswith(normalized):
                return True, 1.0 / rank
        return False, 0.0

    retrieval_rows = [r for r in valid_rows if r.get("expected_doc_id")]
    if retrieval_rows:
        for k in (1, 3, 5):
            hits = 0
            for r in retrieval_rows:
                doc_ids = r.get("retrieved_doc_ids", [])
                hit, _ = _check_hit(doc_ids, r["expected_doc_id"], k)
                if hit:
                    hits += 1
            retrieval[f"hit_at_{k}"] = round(hits / len(retrieval_rows), 4)

        mrr_scores = []
        for r in retrieval_rows:
            doc_ids = r.get("retrieved_doc_ids", [])
            _, rr = _check_hit(doc_ids, r["expected_doc_id"], top_k=max(len(doc_ids), 5))
            mrr_scores.append(rr)
        retrieval["mrr"] = round(sum(mrr_scores) / len(mrr_scores) if mrr_scores else 0.0, 4)
        logger.info("Retrieval hit@3=%.4f, MRR=%.4f", retrieval.get("hit_at_3", 0), retrieval["mrr"])

    # Ragas context_precision and context_recall
    ctx_rows = [
        r for r in valid_rows
        if r.get("retrieved_chunks") and r.get("gigachat_ru_answer") and r.get("ru_expected_answer")
    ]
    if ctx_rows:
        try:
            from datasets import Dataset  # type: ignore[import-untyped]
            from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
            from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore[import-untyped]
            from ragas import evaluate  # type: ignore[import-untyped]
            from ragas.metrics import context_precision, context_recall  # type: ignore[import-untyped]
            from ragas.llms import LangchainLLMWrapper  # type: ignore[import-untyped]
            from ragas.embeddings import LangchainEmbeddingsWrapper  # type: ignore[import-untyped]

            api_key = os.environ.get("OPENROUTER_API_KEY") or _read_env_file_key("OPENROUTER_API_KEY")
            judge_model_id = (
                os.environ.get("RAGAS_JUDGE_MODEL")
                or _read_env_file_key("RAGAS_JUDGE_MODEL")
                or "google/gemini-2.5-flash"
            )
            llm = ChatOpenAI(
                model=judge_model_id,
                openai_api_key=api_key,
                openai_api_base="https://openrouter.ai/api/v1",
                temperature=0,
                default_headers={"HTTP-Referer": "https://adapta.demo", "X-Title": "AdaptaAI RAG Eval"},
            )
            ragas_llm = LangchainLLMWrapper(llm)
            embedding_model_name = os.environ.get("RAGAS_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
            hf_embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)
            ragas_embeddings = LangchainEmbeddingsWrapper(hf_embeddings)
            for m in [context_precision, context_recall]:
                m.llm = ragas_llm  # type: ignore[attr-defined]
                m.embeddings = ragas_embeddings  # type: ignore[attr-defined]

            ctx_dataset = Dataset.from_dict({
                "question": [r["qwen_ru_question"] or r["ru_question_expected"] for r in ctx_rows],
                "answer": [r["gigachat_ru_answer"] for r in ctx_rows],
                "contexts": [[c["chunk_text"] if isinstance(c, dict) else str(c) for c in r["retrieved_chunks"]] for r in ctx_rows],
                "ground_truth": [r["ru_expected_answer"] for r in ctx_rows],
            })
            ctx_result = evaluate(dataset=ctx_dataset, metrics=[context_precision, context_recall], raise_exceptions=False)

            def _extract_mean(res: Any, name: str) -> float | None:
                if hasattr(res, "_repr_dict"):
                    return float(res._repr_dict.get(name, 0))  # noqa: SLF001
                if hasattr(res, "items"):
                    return float(dict(res).get(name, 0))
                try:
                    df = res.to_pandas()
                    if name in df.columns:
                        return float(df[name].mean())
                except Exception:  # noqa: BLE001
                    pass
                return None

            cp = _extract_mean(ctx_result, "context_precision")
            cr = _extract_mean(ctx_result, "context_recall")
            if cp is not None:
                retrieval["context_precision"] = round(cp, 4)
            if cr is not None:
                retrieval["context_recall"] = round(cr, 4)
            logger.info("Retrieval context_precision=%.4f, context_recall=%.4f", cp or 0, cr or 0)
        except ImportError as exc:
            logger.warning("Ragas not available for context metrics: %s", exc)

    metrics["retrieval"] = retrieval

    # -------------------------------------------------------------------------
    # Generation: Ragas faithfulness, answer_relevancy, answer_correctness, semantic_similarity
    # -------------------------------------------------------------------------
    gen_rows = [
        r for r in valid_rows
        if r.get("gigachat_ru_answer") and r.get("ru_expected_answer")
    ]
    generation: dict[str, float] = {}

    if gen_rows:
        try:
            from datasets import Dataset  # type: ignore[import-untyped]
            from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
            from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore[import-untyped]
            from ragas import evaluate  # type: ignore[import-untyped]
            from ragas.metrics import (  # type: ignore[import-untyped]
                answer_correctness,
                answer_relevancy,
                answer_similarity,
                faithfulness,
            )
            from ragas.llms import LangchainLLMWrapper  # type: ignore[import-untyped]
            from ragas.embeddings import LangchainEmbeddingsWrapper  # type: ignore[import-untyped]

            api_key = os.environ.get("OPENROUTER_API_KEY") or _read_env_file_key("OPENROUTER_API_KEY")
            judge_model_id = (
                os.environ.get("RAGAS_JUDGE_MODEL")
                or _read_env_file_key("RAGAS_JUDGE_MODEL")
                or "google/gemini-2.5-flash"
            )
            llm = ChatOpenAI(
                model=judge_model_id,
                openai_api_key=api_key,
                openai_api_base="https://openrouter.ai/api/v1",
                temperature=0,
                default_headers={"HTTP-Referer": "https://adapta.demo", "X-Title": "AdaptaAI RAG Eval"},
            )
            ragas_llm = LangchainLLMWrapper(llm)
            embedding_model_name = os.environ.get("RAGAS_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
            hf_embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)
            ragas_embeddings = LangchainEmbeddingsWrapper(hf_embeddings)

            gen_metrics = [faithfulness, answer_relevancy, answer_correctness, answer_similarity]
            for m in gen_metrics:
                m.llm = ragas_llm  # type: ignore[attr-defined]
                m.embeddings = ragas_embeddings  # type: ignore[attr-defined]

            ctx_for_gen = [
                [c["chunk_text"] if isinstance(c, dict) else str(c) for c in r.get("retrieved_chunks", [])]
                for r in gen_rows
            ]
            gen_dataset = Dataset.from_dict({
                "question": [r["qwen_ru_question"] or r["ru_question_expected"] for r in gen_rows],
                "answer": [r["gigachat_ru_answer"] for r in gen_rows],
                "contexts": ctx_for_gen,
                "ground_truth": [r["ru_expected_answer"] for r in gen_rows],
            })
            gen_result = evaluate(dataset=gen_dataset, metrics=gen_metrics, raise_exceptions=False)

            def _gen_mean(name: str) -> float | None:
                if hasattr(gen_result, "_repr_dict"):
                    v = gen_result._repr_dict.get(name)  # noqa: SLF001
                    return float(v) if v is not None else None
                if hasattr(gen_result, "items"):
                    v = dict(gen_result).get(name)
                    return float(v) if v is not None else None
                try:
                    df = gen_result.to_pandas()
                    if name in df.columns:
                        return float(df[name].mean())
                except Exception:  # noqa: BLE001
                    pass
                return None

            for metric_name in ["faithfulness", "answer_relevancy", "answer_correctness"]:
                v = _gen_mean(metric_name)
                if v is not None:
                    generation[metric_name] = round(v, 4)

            sim = _gen_mean("answer_similarity") or _gen_mean("semantic_similarity")
            if sim is not None:
                generation["semantic_similarity"] = round(sim, 4)

            logger.info("Generation metrics: %s", generation)
        except ImportError as exc:
            logger.warning("Ragas not available for generation metrics: %s", exc)

    metrics["generation"] = generation

    # -------------------------------------------------------------------------
    # Step B: chrF + cosine round-trip (gigachat_ru_answer vs qwen_back_ru_answer)
    # -------------------------------------------------------------------------
    step_b_rows = [
        r for r in valid_rows
        if r.get("gigachat_ru_answer") and r.get("qwen_back_ru_answer")
    ]
    step_b: dict[str, float] = {}

    if step_b_rows:
        try:
            import sacrebleu  # type: ignore[import-untyped]

            hyps = [r["qwen_back_ru_answer"] for r in step_b_rows]
            refs = [[r["gigachat_ru_answer"] for r in step_b_rows]]
            chrf_b = sacrebleu.corpus_chrf(hyps, refs)
            step_b["chrf_roundtrip"] = round(float(chrf_b.score) / 100.0, 4)
            logger.info("Step B chrF_roundtrip=%.4f", step_b["chrf_roundtrip"])
        except ImportError:
            logger.warning("sacrebleu not installed — skipping Step B chrF")

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            emb_model_b = SentenceTransformer(
                os.environ.get(
                    "RAGAS_EMBEDDING_MODEL",
                    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                )
            )
            hyp_embs_b = emb_model_b.encode([r["qwen_back_ru_answer"] for r in step_b_rows], normalize_embeddings=True)
            ref_embs_b = emb_model_b.encode([r["gigachat_ru_answer"] for r in step_b_rows], normalize_embeddings=True)
            cosines_b = [float(np.dot(h, r)) for h, r in zip(hyp_embs_b, ref_embs_b)]
            step_b["cosine_roundtrip"] = round(sum(cosines_b) / len(cosines_b), 4)
            logger.info("Step B cosine_roundtrip=%.4f", step_b["cosine_roundtrip"])
        except ImportError:
            logger.warning("sentence_transformers not installed — skipping Step B cosine")

    metrics["step_b"] = step_b

    # -------------------------------------------------------------------------
    # E2E: cross-lingual cosine between qwen_hi_answer and ru_expected_answer
    # -------------------------------------------------------------------------
    e2e_rows = [
        r for r in valid_rows
        if r.get("qwen_hi_answer") and r.get("ru_expected_answer")
    ]
    e2e: dict[str, float] = {}

    if e2e_rows:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            emb_model_e = SentenceTransformer(
                os.environ.get(
                    "RAGAS_EMBEDDING_MODEL",
                    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                )
            )
            hi_embs = emb_model_e.encode([r["qwen_hi_answer"] for r in e2e_rows], normalize_embeddings=True)
            ru_embs = emb_model_e.encode([r["ru_expected_answer"] for r in e2e_rows], normalize_embeddings=True)
            e2e_cosines = [float(np.dot(h, r)) for h, r in zip(hi_embs, ru_embs)]
            e2e["hi_to_ru_cosine"] = round(sum(e2e_cosines) / len(e2e_cosines), 4)
            logger.info("E2E hi_to_ru_cosine=%.4f", e2e["hi_to_ru_cosine"])
        except ImportError:
            logger.warning("sentence_transformers not installed — skipping E2E cosine")

    metrics["e2e"] = e2e

    # Performance
    latencies = [r["latency_ms"] for r in perstep_results if r.get("latency_ms") is not None]
    if latencies:
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        metrics["performance"] = {
            "latency_p50_ms": round(sorted_lat[int(n * 0.50)], 1),
            "latency_p95_ms": round(sorted_lat[min(int(n * 0.95), n - 1)], 1),
            "latency_mean_ms": round(sum(sorted_lat) / n, 1),
        }

    return metrics


def write_perstep_report(
    metrics: dict[str, Any],
    raw_data: list[dict[str, Any]],
    output_dir: Path,
    pipeline_label: str = "qwen_gigachat_full_per_step",
) -> None:
    """Write raw.csv, ragas_metrics.json, report.md for per-step run."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # raw.csv with per-step columns
    csv_path = output_dir / "raw.csv"
    fieldnames = [
        "hi_question", "ru_question_expected", "qwen_ru_question",
        "retrieved_doc_ids", "expected_doc_id",
        "gigachat_ru_answer", "ru_expected_answer",
        "qwen_hi_answer", "qwen_back_ru_answer",
        "latency_ms", "is_timeout",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in raw_data:
            writer.writerow({
                "hi_question": row.get("hi_question", ""),
                "ru_question_expected": row.get("ru_question_expected", ""),
                "qwen_ru_question": row.get("qwen_ru_question", ""),
                "retrieved_doc_ids": json.dumps(row.get("retrieved_doc_ids", []), ensure_ascii=False),
                "expected_doc_id": row.get("expected_doc_id", ""),
                "gigachat_ru_answer": row.get("gigachat_ru_answer", ""),
                "ru_expected_answer": row.get("ru_expected_answer", ""),
                "qwen_hi_answer": row.get("qwen_hi_answer", ""),
                "qwen_back_ru_answer": row.get("qwen_back_ru_answer", ""),
                "latency_ms": row.get("latency_ms", ""),
                "is_timeout": row.get("is_timeout", False),
            })
    logger.info("raw.csv (per-step) written: %s", csv_path)

    # ragas_metrics.json
    enriched: dict[str, Any] = {
        "pipeline_label": pipeline_label,
        "lang": "hi",
        **metrics,
    }
    json_path = output_dir / "ragas_metrics.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    logger.info("ragas_metrics.json (per-step) written: %s", json_path)

    # report.md
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    step_a = metrics.get("step_a", {})
    retrieval = metrics.get("retrieval", {})
    generation = metrics.get("generation", {})
    step_b = metrics.get("step_b", {})
    e2e = metrics.get("e2e", {})
    perf = metrics.get("performance", {})

    def _f(val: Any) -> str:
        if val is None or val == "":
            return "—"
        if isinstance(val, float):
            return f"{val:.3f}"
        return str(val)

    # Find top-3 failure examples (questions with lowest gigachat answer correctness or timeout)
    failure_examples: list[dict[str, Any]] = []
    for row in raw_data:
        if row.get("is_timeout"):
            failure_examples.append(row)
        elif not row.get("gigachat_ru_answer"):
            failure_examples.append(row)
    if len(failure_examples) < 3:
        # Add rows with short GigaChat answers (likely poor quality)
        for row in raw_data:
            if not row.get("is_timeout") and row not in failure_examples:
                gc_ans = row.get("gigachat_ru_answer", "")
                exp_ans = row.get("ru_expected_answer", "")
                if gc_ans and exp_ans and len(gc_ans) < len(exp_ans) // 2:
                    failure_examples.append(row)
                    if len(failure_examples) >= 3:
                        break
    failure_examples = failure_examples[:5]

    failure_section = ""
    for j, row in enumerate(failure_examples, start=1):
        failure_section += f"\n### Пример {j}\n"
        failure_section += f"- **hi-вопрос:** {row.get('hi_question', '—')}\n"
        failure_section += f"- **Qwen ru-перевод (Step A):** {row.get('qwen_ru_question', '—')}\n"
        failure_section += f"- **Ожидаемый doc:** `{row.get('expected_doc_id', '—')}`\n"
        failure_section += f"- **Найденные doc'ы:** {json.dumps(row.get('retrieved_doc_ids', []), ensure_ascii=False)}\n"
        failure_section += f"- **GigaChat ответ:** {str(row.get('gigachat_ru_answer', '—'))[:200]}\n"
        failure_section += f"- **Эталон:** {str(row.get('ru_expected_answer', '—'))[:200]}\n"
        if row.get("is_timeout"):
            failure_section += "- **Проблема:** GigaChat timeout\n"
        elif not row.get("gigachat_ru_answer"):
            failure_section += "- **Проблема:** Пустой ответ GigaChat (нет контекста)\n"
        else:
            failure_section += "- **Проблема:** Ответ значительно короче эталона\n"

    e2e_cosine = e2e.get("hi_to_ru_cosine")
    main_drop_step = "неизвестно"
    step_a_cosine = step_a.get("cosine")
    hit3 = retrieval.get("hit_at_3")
    gen_faith = generation.get("faithfulness")
    step_b_chrf = step_b.get("chrf_roundtrip")
    if step_a_cosine is not None and step_a_cosine < 0.7:
        main_drop_step = "Step A (Qwen hi→ru — семантические потери при переводе)"
    elif hit3 is not None and hit3 < 0.7:
        main_drop_step = "Retrieval (неточный поиск после Qwen-перевода)"
    elif gen_faith is not None and gen_faith < 0.7:
        main_drop_step = "Generation (GigaChat галлюцинирует или не находит ответ)"
    elif step_b_chrf is not None and step_b_chrf < 0.6:
        main_drop_step = "Step B (Qwen ru→hi — потери при обратном переводе)"
    elif hit3 is not None and hit3 >= 0.9:
        main_drop_step = "Generation (GigaChat SGR timeout — step A и retrieval работают отлично)"

    lines = [
        "# RAG hi-pipeline · per-step report",
        "",
        f"**Дата:** {now}",
        f"**Вопросов:** {metrics.get('questions', 0)} | Timeout'ов: {metrics.get('questions_timeout', 0)}",
        "",
        "## TL;DR",
        "",
        f"Полный hi-pipeline даёт e2e_cosine {_f(e2e_cosine)}. "
        f"Главная просадка — на шаге: {main_drop_step}.",
        "",
        "## Pipeline schema",
        "",
        "```",
        "[1] hi-вопрос",
        "       │",
        "       │  Step A: Qwen(hi→ru)",
        "       ▼",
        "[2] qwen_ru_question                          ← мерим А",
        "       │",
        "       │  Retrieval: multilingual-mpnet → ChromaDB top-3",
        "       ▼",
        "[3] retrieved_chunks                          ← мерим Retrieval",
        "       │",
        "       │  Generation: GigaChat SGR",
        "       ▼",
        "[4] gigachat_ru_answer                        ← мерим Generation",
        "       │",
        "       │  Step B: Qwen(ru→hi)",
        "       ▼",
        "[5] qwen_hi_answer                            ← мерим B (через round-trip)",
        "```",
        "",
        "## Step-by-step метрики",
        "",
        "### Step A — Qwen hi→ru",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| chrF | {_f(step_a.get('chrf'))} |",
        f"| BLEU-4 | {_f(step_a.get('bleu'))} |",
        f"| Semantic cosine | {_f(step_a.get('cosine'))} |",
        "",
        "Насколько Qwen сохранил смысл вопроса при переводе с хинди на русский. "
        "1.0 = идеальный перевод, ниже 0.7 = смысловые потери.",
        "",
        "### Retrieval (на ru-вопросах после Step A)",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| hit@1 | {_f(retrieval.get('hit_at_1'))} |",
        f"| hit@3 | {_f(retrieval.get('hit_at_3'))} |",
        f"| hit@5 | {_f(retrieval.get('hit_at_5'))} |",
        f"| MRR | {_f(retrieval.get('mrr'))} |",
        f"| context_precision | {_f(retrieval.get('context_precision'))} |",
        f"| context_recall | {_f(retrieval.get('context_recall'))} |",
        "",
        "### Generation — GigaChat",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| faithfulness | {_f(generation.get('faithfulness'))} |",
        f"| answer_relevancy | {_f(generation.get('answer_relevancy'))} |",
        f"| answer_correctness | {_f(generation.get('answer_correctness'))} |",
        f"| semantic_similarity | {_f(generation.get('semantic_similarity'))} |",
        "",
        "### Step B — Qwen ru→hi (round-trip)",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| chrF roundtrip | {_f(step_b.get('chrf_roundtrip'))} |",
        f"| Cosine roundtrip | {_f(step_b.get('cosine_roundtrip'))} |",
        "",
        "Round-trip: обратный перевод hi→ru → сравниваем с gigachat_ru_answer. "
        "Если ≥ 0.85 — Qwen не искажает смысл.",
        "",
        "### End-to-end",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| hi_answer ↔ ru_expected cosine | {_f(e2e_cosine)} |",
        "",
        "## Производительность",
        "",
        f"- latency_p50_ms: {_f(perf.get('latency_p50_ms'))}",
        f"- latency_p95_ms: {_f(perf.get('latency_p95_ms'))}",
        f"- latency_mean_ms: {_f(perf.get('latency_mean_ms'))}",
        "",
        "## Где теряем точность (топ-3)",
        "",
        f"1. **Step A** (chrF {_f(step_a.get('chrf'))}, cosine {_f(step_a.get('cosine'))}) — "
        "Qwen переводит хинди-вопрос в русский; потери семантики напрямую влияют на retrieval.",
        f"2. **Retrieval** (hit@3 {_f(retrieval.get('hit_at_3'))}) — "
        "если Qwen перевёл неточно, ChromaDB не найдёт правильный документ.",
        f"3. **Step B** (chrF_roundtrip {_f(step_b.get('chrf_roundtrip'))}) — "
        "обратный перевод GigaChat-ответа на хинди теряет часть специфичных терминов.",
        "",
        "## Конкретные примеры провалов",
        failure_section,
        "",
        "## Рекомендации",
        "",
        "- **Улучшить Step A:** использовать system-prompt с контекстом (банковская/миграционная лексика) для Qwen.",
        "- **Улучшить Retrieval:** добавить hybrid retrieval (dense + BM25) для устойчивости к переводным погрешностям.",
        "- **Улучшить Step B:** fine-tuned перевод на финансовые термины, или оставить ключевые слова транслитерированными.",
        "- **Расширить golden_set:** 100+ вопросов с native-speaker review для статистической надёжности.",
        "",
        "---",
        f"*Генерировано: eval_rag.py per-step | Judge LLM: OpenRouter {os.environ.get('RAGAS_JUDGE_MODEL','google/gemini-2.5-flash')} | Embeddings: multilingual-mpnet*",
    ]
    report_md = "\n".join(lines) + "\n"
    report_path = output_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("report.md (per-step) written: %s", report_path)


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


def compute_metrics(eval_results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute Ragas metrics on eval results using OpenRouter as judge LLM."""
    try:
        from datasets import Dataset  # type: ignore[import-untyped]
        from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
        from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore[import-untyped]
        from ragas import evaluate  # type: ignore[import-untyped]
        from ragas.metrics import (  # type: ignore[import-untyped]
            answer_correctness,
            answer_relevancy,
            answer_similarity,
            context_precision,
            context_recall,
            faithfulness,
        )
        from ragas.llms import LangchainLLMWrapper  # type: ignore[import-untyped]
        from ragas.embeddings import LangchainEmbeddingsWrapper  # type: ignore[import-untyped]
    except ImportError as exc:
        logger.error(
            "Ragas/datasets/langchain-openai not installed. "
            "Run: make rag-eval-setup\nError: %s",
            exc,
        )
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY") or _read_env_file_key("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not found. Export it before running eval.")
        sys.exit(1)

    judge_model_id = (
        os.environ.get("RAGAS_JUDGE_MODEL")
        or _read_env_file_key("RAGAS_JUDGE_MODEL")
        or "google/gemini-2.5-flash"
    )

    logger.info("Initializing Ragas with judge model: %s", judge_model_id)

    llm = ChatOpenAI(
        model=judge_model_id,
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0,
        default_headers={
            "HTTP-Referer": "https://adapta.demo",
            "X-Title": "AdaptaAI RAG Eval",
        },
    )
    ragas_llm = LangchainLLMWrapper(llm)

    embedding_model_name = os.environ.get(
        "RAGAS_EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    )
    logger.info("Loading embeddings: %s", embedding_model_name)
    hf_embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)
    ragas_embeddings = LangchainEmbeddingsWrapper(hf_embeddings)

    # Split rows: context-dependent vs answer-only metrics
    rows_with_context = [r for r in eval_results if r["contexts"]]
    rows_all = eval_results

    def _make_dataset(rows: list[dict[str, Any]]) -> "Dataset":
        return Dataset.from_dict(
            {
                "question": [r["question"] for r in rows],
                "answer": [r["answer"] for r in rows],
                "contexts": [r["contexts"] for r in rows],
                "ground_truth": [r["expected_answer"] for r in rows],
            }
        )

    metrics_with_context = [
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    ]
    metrics_no_context = [
        answer_correctness,
        answer_similarity,
    ]

    results_dict: dict[str, float] = {}

    # Assign judge LLM + embeddings to each metric
    for m in metrics_with_context + metrics_no_context:
        m.llm = ragas_llm  # type: ignore[attr-defined]
        m.embeddings = ragas_embeddings  # type: ignore[attr-defined]

    # Try to add NoiseSensitivity if ragas 0.2 supports it
    noise_metric = None
    try:
        from ragas.metrics import NoiseSensitivity  # type: ignore[import-untyped]
        noise_metric = NoiseSensitivity()
        noise_metric.llm = ragas_llm  # type: ignore[attr-defined]
        noise_metric.embeddings = ragas_embeddings  # type: ignore[attr-defined]
        logger.info("NoiseSensitivity metric available — will compute if context rows exist")
    except ImportError:
        logger.warning(
            "NoiseSensitivity not available in this ragas version — skipping. "
            "Upgrade to ragas>=0.2 to enable."
        )

    def _extract_scores(result: Any) -> dict[str, float]:
        """Extract mean scores from ragas 0.2 EvaluationResult."""
        # ragas 0.2: EvaluationResult has _repr_dict with mean scores
        if hasattr(result, "_repr_dict"):
            return {k: float(v) for k, v in result._repr_dict.items()}  # noqa: SLF001
        # ragas 0.1 compat: dict-like
        if hasattr(result, "items"):
            return {k: float(v) for k, v in result.items()}
        # fallback: try to_pandas
        try:
            df = result.to_pandas()
            numeric_cols = df.select_dtypes("number").columns
            return {col: float(df[col].mean()) for col in numeric_cols}
        except Exception:  # noqa: BLE001
            logger.warning("Could not extract scores from EvaluationResult: %s", type(result))
            return {}

    if rows_with_context:
        logger.info("Computing context-dependent metrics on %d rows...", len(rows_with_context))
        ds_ctx = _make_dataset(rows_with_context)
        score_ctx = evaluate(
            dataset=ds_ctx,
            metrics=metrics_with_context,
            raise_exceptions=False,
        )
        results_dict.update(_extract_scores(score_ctx))

        # NoiseSensitivity (optional)
        if noise_metric is not None:
            try:
                score_noise = evaluate(
                    dataset=ds_ctx,
                    metrics=[noise_metric],
                    raise_exceptions=False,
                )
                results_dict.update(_extract_scores(score_noise))
                logger.info("NoiseSensitivity computed successfully")
            except Exception as exc:  # noqa: BLE001
                logger.warning("NoiseSensitivity computation failed: %s", exc)

    logger.info("Computing answer quality metrics on %d rows...", len(rows_all))
    ds_all = _make_dataset(rows_all)
    score_all = evaluate(
        dataset=ds_all,
        metrics=metrics_no_context,
        raise_exceptions=False,
    )
    results_dict.update(_extract_scores(score_all))

    # Latency stats
    results_dict.update(_compute_latency_stats(eval_results))

    # Cost estimation
    results_dict.update(_compute_cost(eval_results))

    # Retrieval metrics (hit@3, MRR)
    results_dict.update(_compute_retrieval_metrics(eval_results, k=3))

    # NLG metrics (ROUGE-L, BLEU-4)
    results_dict.update(_compute_nlg_metrics(eval_results))

    logger.info("All metrics computed: %s", results_dict)
    return results_dict


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------


def write_report(
    metrics: dict[str, float],
    raw_data: list[dict[str, Any]],
    output_dir: Path,
    pipeline_label: str = "default",
    lang: str = "ru",
    golden_set_path: Path | None = None,
) -> None:
    """Write raw.csv, ragas_metrics.json, report.md to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # raw.csv — includes latency_ms, tokens_in, tokens_out
    csv_path = output_dir / "raw.csv"
    fieldnames = [
        "question", "expected_answer", "expected_doc_id",
        "answer", "contexts", "latency_ms", "tokens_in", "tokens_out",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in raw_data:
            writer.writerow(
                {
                    "question": row.get("question", ""),
                    "expected_answer": row.get("expected_answer", ""),
                    "expected_doc_id": row.get("expected_doc_id", ""),
                    "answer": row.get("answer", ""),
                    "contexts": " | ".join(
                        str(c) for c in row.get("contexts", [])
                    ),
                    "latency_ms": row.get("latency_ms", ""),
                    "tokens_in": row.get("tokens_in", ""),
                    "tokens_out": row.get("tokens_out", ""),
                }
            )
    logger.info("raw.csv written: %s", csv_path)

    # ragas_metrics.json — enrich with pipeline metadata
    enriched_metrics: dict[str, Any] = dict(metrics)
    enriched_metrics["pipeline_label"] = pipeline_label
    enriched_metrics["lang"] = lang
    enriched_metrics["golden_set_path"] = str(golden_set_path) if golden_set_path else ""

    json_path = output_dir / "ragas_metrics.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(enriched_metrics, f, ensure_ascii=False, indent=2)
    logger.info("ragas_metrics.json written: %s", json_path)

    # report.md
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n_questions = len(raw_data)
    n_with_answer = sum(1 for r in raw_data if r.get("answer"))
    n_with_context = sum(1 for r in raw_data if r.get("contexts"))

    def _fmt(val: float | None) -> str:
        if val is None:
            return "-"
        return f"{val:.3f}"

    def _fmt_int(val: float | None) -> str:
        if val is None:
            return "-"
        return str(int(val))

    # ragas 0.2 may use "semantic_similarity" internally instead of "answer_similarity"
    sim_score = metrics.get("answer_similarity") or metrics.get("semantic_similarity")

    # Core Ragas metrics table
    ragas_rows = [
        ("faithfulness", "Не выдумывает факты", metrics.get("faithfulness")),
        ("answer_relevancy", "Отвечает на вопрос", metrics.get("answer_relevancy")),
        ("context_precision", "Чанки релевантны", metrics.get("context_precision")),
        ("context_recall", "Чанки покрывают ответ", metrics.get("context_recall")),
        ("answer_correctness", "Совпадение с эталоном", metrics.get("answer_correctness")),
        ("semantic_similarity", "Семантическая близость", sim_score),
    ]

    table_ragas = "| Метрика | Описание | Значение |\n|---|---|---|\n"
    table_ragas += "\n".join(
        f"| `{name}` | {desc} | {_fmt(val)} |" for name, desc, val in ragas_rows
    )

    avg_values = [v for _, _, v in ragas_rows if v is not None]
    avg = sum(avg_values) / len(avg_values) if avg_values else 0.0

    # Performance section
    perf_lines = []
    if metrics.get("latency_p50_ms") is not None:
        perf_lines.append(f"- latency_p50_ms: {_fmt(metrics.get('latency_p50_ms'))}")
        perf_lines.append(f"- latency_p95_ms: {_fmt(metrics.get('latency_p95_ms'))}")
        perf_lines.append(f"- latency_mean_ms: {_fmt(metrics.get('latency_mean_ms'))}")
    if metrics.get("cost_total_usd") is not None:
        perf_lines.append(f"- cost_total_usd: ${metrics.get('cost_total_usd', 0):.6f}")
        cost_rub = metrics.get("cost_total_rub")
        if cost_rub is not None:
            perf_lines.append(f"- cost_total_rub: {cost_rub:.2f} ₽")
        perf_lines.append(
            f"- total_tokens_in: {_fmt_int(metrics.get('total_tokens_in'))} / "
            f"tokens_out: {_fmt_int(metrics.get('total_tokens_out'))}"
        )
        generators_val = metrics.get("generators")
        if generators_val:
            perf_lines.append(f"- generators: `{generators_val}`")
    perf_section = (
        "## Performance\n\n" + "\n".join(perf_lines)
        if perf_lines
        else "## Performance\n\n_Latency data not available (run skipped metrics)._"
    )

    # Retrieval section
    retrieval_lines = []
    if metrics.get("retrieval_hit_at_3") is not None:
        retrieval_lines.append(f"- retrieval_hit_at_3: {_fmt(metrics.get('retrieval_hit_at_3'))}")
        retrieval_lines.append(f"- retrieval_mrr: {_fmt(metrics.get('retrieval_mrr'))}")
    retrieval_section = (
        "## Retrieval\n\n" + "\n".join(retrieval_lines)
        if retrieval_lines
        else "## Retrieval\n\n_Retrieval metrics not computed._"
    )

    # NLG section
    nlg_lines = []
    if metrics.get("rouge_l_recall") is not None:
        nlg_lines.append(f"- ROUGE-L recall: {_fmt(metrics.get('rouge_l_recall'))}")
    if metrics.get("bleu_4") is not None:
        nlg_lines.append(f"- BLEU-4: {_fmt(metrics.get('bleu_4'))}")
    nlg_section = (
        "## NLG\n\n" + "\n".join(nlg_lines)
        if nlg_lines
        else "## NLG\n\n_ROUGE/BLEU not computed (rouge_score/sacrebleu not installed)._"
    )

    # Robustness section
    robustness_lines = []
    if metrics.get("noise_sensitivity") is not None:
        robustness_lines.append(
            f"- noise_sensitivity: {_fmt(metrics.get('noise_sensitivity'))} "
            "(0=устойчив, 1=чувствителен к шуму)"
        )
    robustness_section = (
        "## Robustness\n\n" + "\n".join(robustness_lines)
        if robustness_lines
        else "## Robustness\n\n_NoiseSensitivity недоступна в текущей версии ragas._"
    )

    # Pipeline section
    pipeline_description = {
        "default": "Стандартный ru-путь: ru-вопрос → retrieval → GigaChat → ru-ответ.",
        "qwen_gigachat": "hi-вопрос → Qwen(hi→ru) → retrieval → GigaChat → ru-ответ. Без Step B (обратный перевод пропущен).",
    }.get(pipeline_label, pipeline_label)

    lines = [
        "# AdaptaAI RAG Eval Report",
        "",
        f"**Дата:** {now}",
        f"**Вопросов:** {n_questions} / с ответами: {n_with_answer} / с контекстом: {n_with_context}",
        "",
        "## Pipeline",
        "",
        f"**Название:** `{pipeline_label}`",
        f"**Язык запросов:** `{lang}`",
        f"**Описание:** {pipeline_description}",
        "",
        "## Метрики Ragas",
        "",
        table_ragas,
        "",
        f"**Среднее по основным метрикам: {_fmt(avg)}**",
        "",
        perf_section,
        "",
        retrieval_section,
        "",
        nlg_section,
        "",
        robustness_section,
        "",
        "## Интерпретация",
        "",
        "- `faithfulness >= 0.8` -- модель не галлюцинирует.",
        "- `context_recall >= 0.7` -- RAG-retriever находит нужные чанки.",
        "- `answer_correctness >= 0.7` -- ответы соответствуют эталонам golden set.",
        "- `retrieval_hit_at_3 >= 0.9` -- retriever находит нужный документ в топ-3.",
        "- `latency_p95_ms < 10000` -- 95% запросов укладываются в 10 секунд.",
        "",
        "## Файлы прогона",
        "",
        "- `raw.csv` -- сырые ответы на каждый вопрос (+ latency_ms, tokens)",
        "- `ragas_metrics.json` -- все метрики в машиночитаемом формате",
        "- `report.md` -- этот файл",
        "",
        "---",
        f"*Генерировано: eval_rag.py | Judge LLM: OpenRouter {os.environ.get('RAGAS_JUDGE_MODEL','google/gemini-2.5-flash')} | Embeddings: paraphrase-multilingual-mpnet-base-v2*",
    ]
    report_md = "\n".join(lines) + "\n"

    report_path = output_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("report.md written: %s", report_path)
    logger.info("Run output dir: %s", output_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _make_run_dir(label: str | None = None) -> Path:
    """Return a timestamped run directory path.

    If label is provided (non-empty), the directory is named
    ``<timestamp>_<label>``, e.g. ``2026-05-29T120000Z_qwen_only``.
    Otherwise only the timestamp is used.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    if label and label not in ("default", ""):
        return _RUNS_DIR / f"{ts}_{label}"
    return _RUNS_DIR / ts


def cmd_build_set(args: argparse.Namespace) -> None:
    source_docs = Path(args.source_docs) if args.source_docs else _SOURCE_DOCS
    output = Path(args.output) if args.output else _GOLDEN_SET_DEFAULT
    build_golden_set(
        source_docs=source_docs,
        output=output,
        questions_per_doc=args.questions_per_doc,
        force=args.force,
    )


def cmd_run(args: argparse.Namespace) -> None:
    golden_set_path = Path(args.golden_set) if args.golden_set else _GOLDEN_SET_DEFAULT
    lang: str = getattr(args, "lang", "ru") or "ru"
    pipeline_label: str = getattr(args, "label", "default") or "default"
    run_dir = Path(args.run_dir) if args.run_dir else _make_run_dir(label=pipeline_label)
    run_dir.mkdir(parents=True, exist_ok=True)

    pipeline_mode_arg: str | None = getattr(args, "pipeline_mode", None) or None
    qwen_model_arg: str | None = getattr(args, "qwen_model", None) or None

    raw_data = run_eval(
        golden_set_path=golden_set_path,
        prod_url=args.prod_url,
        demo_password=getattr(args, "demo_password", None),
        jwt_token=getattr(args, "jwt_token", None),
        lang=lang,
        pipeline_mode=pipeline_mode_arg,
        qwen_model=qwen_model_arg,
    )

    # Save raw data before compute in case metrics step fails
    raw_json_path = run_dir / "raw_responses.json"
    with raw_json_path.open("w", encoding="utf-8") as f:
        serializable = [
            {k: v for k, v in r.items() if k != "raw_response"} for r in raw_data
        ]
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    logger.info("Raw responses saved to %s", raw_json_path)

    if args.skip_metrics:
        logger.info("--skip-metrics set, skipping Ragas computation")
        write_report(
            metrics={},
            raw_data=raw_data,
            output_dir=run_dir,
            pipeline_label=pipeline_label,
            lang=lang,
            golden_set_path=golden_set_path,
        )
        return

    metrics = compute_metrics(raw_data)
    write_report(
        metrics=metrics,
        raw_data=raw_data,
        output_dir=run_dir,
        pipeline_label=pipeline_label,
        lang=lang,
        golden_set_path=golden_set_path,
    )


def cmd_report(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    raw_json_path = run_dir / "raw_responses.json"
    if not raw_json_path.exists():
        logger.error("raw_responses.json not found in %s", run_dir)
        sys.exit(1)

    with raw_json_path.open(encoding="utf-8") as f:
        raw_data: list[dict[str, Any]] = json.load(f)

    if args.recompute_metrics:
        metrics = compute_metrics(raw_data)
    else:
        metrics_path = run_dir / "ragas_metrics.json"
        if metrics_path.exists():
            with metrics_path.open(encoding="utf-8") as f:
                metrics = json.load(f)
        else:
            logger.warning("No ragas_metrics.json found, recomputing...")
            metrics = compute_metrics(raw_data)

    write_report(metrics=metrics, raw_data=raw_data, output_dir=run_dir)


def cmd_run_perstep(args: argparse.Namespace) -> None:
    """CLI handler for run-perstep command."""
    golden_hi_path = (
        Path(args.golden_set_hi)
        if args.golden_set_hi
        else _REPO_ROOT / "data" / "rag_eval" / "golden_set_hi.yaml"
    )
    golden_ru_path = (
        Path(args.golden_set_ru)
        if args.golden_set_ru
        else _GOLDEN_SET_DEFAULT
    )
    run_dir = Path(args.run_dir) if args.run_dir else _make_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_data = run_eval_perstep(
        golden_set_hi_path=golden_hi_path,
        golden_set_ru_path=golden_ru_path,
        prod_url=args.prod_url,
        demo_password=getattr(args, "demo_password", None),
        jwt_token=getattr(args, "jwt_token", None),
    )

    # Save raw data
    raw_json_path = run_dir / "raw_responses.json"
    with raw_json_path.open("w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    logger.info("Raw per-step responses saved to %s", raw_json_path)

    if getattr(args, "skip_metrics", False):
        logger.info("--skip-metrics set, skipping metrics computation")
        write_perstep_report(
            metrics={"questions": len(raw_data), "questions_timeout": sum(1 for r in raw_data if r.get("is_timeout"))},
            raw_data=raw_data,
            output_dir=run_dir,
        )
        return

    metrics = compute_perstep_metrics(raw_data)
    write_perstep_report(
        metrics=metrics,
        raw_data=raw_data,
        output_dir=run_dir,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AdaptaAI RAG evaluation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # build-set
    p_build = subparsers.add_parser("build-set", help="Generate golden set from source docs")
    p_build.add_argument(
        "--source-docs",
        help="Path to source_docs dir (default: data/rag_eval/source_docs)",
    )
    p_build.add_argument("--output", help="Output golden_set.yaml path")
    p_build.add_argument(
        "--questions-per-doc",
        type=int,
        default=5,
        help="Q&A pairs per doc (default: 5)",
    )
    p_build.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing golden_set.yaml",
    )
    p_build.set_defaults(func=cmd_build_set)

    # run
    p_run = subparsers.add_parser("run", help="Run eval against prod API and compute metrics")
    p_run.add_argument("--golden-set", help="Path to golden_set.yaml")
    p_run.add_argument(
        "--prod-url",
        required=True,
        help="Prod base URL, e.g. http://localhost:8080",
    )
    p_run.add_argument("--demo-password", help="Demo user password to obtain JWT")
    p_run.add_argument("--jwt-token", help="JWT token (alternative to --demo-password)")
    p_run.add_argument(
        "--run-dir",
        help="Output run directory (default: auto timestamped)",
    )
    p_run.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip Ragas metrics computation (save raw data only)",
    )
    p_run.add_argument(
        "--lang",
        default="ru",
        choices=["ru", "hi"],
        help=(
            "Language for chat requests. 'ru' (default): send question in Russian. "
            "'hi': send question in Hindi with skip_translate_response=True "
            "(answer stays in Russian for comparison against ru etalons)."
        ),
    )
    p_run.add_argument(
        "--label",
        default="default",
        help=(
            "Pipeline label for report and ragas_metrics.json. "
            "E.g. 'qwen_gigachat' for hi-pipeline. Default: 'default'."
        ),
    )
    p_run.add_argument(
        "--pipeline-mode",
        choices=["both", "qwen_only", "gigachat_only"],
        default=None,
        dest="pipeline_mode",
        help=(
            "Override pipeline mode for every request in this run. "
            "'both' (default on server): full pipeline with Qwen Steps A/B + GigaChat. "
            "'qwen_only': Qwen handles generation (combine with --qwen-model). "
            "'gigachat_only': GigaChat only, Steps A/B skipped. "
            "When omitted, server-side EVAL_PIPELINE_MODE env setting applies."
        ),
    )
    p_run.add_argument(
        "--qwen-model",
        default=None,
        dest="qwen_model",
        metavar="SLUG",
        help=(
            "Override Qwen model slug for this run "
            "(e.g. 'qwen/qwen3-235b-a22b', 'qwen/qwen-2.5-72b-instruct'). "
            "Used only when --pipeline-mode=qwen_only. "
            "When omitted, server-side QWEN_MODEL env setting applies."
        ),
    )
    p_run.set_defaults(func=cmd_run)

    # report
    p_report = subparsers.add_parser("report", help="Generate report from existing run dir")
    p_report.add_argument("--run-dir", required=True, help="Path to run directory")
    p_report.add_argument(
        "--recompute-metrics",
        action="store_true",
        help="Recompute Ragas metrics from saved raw data",
    )
    p_report.set_defaults(func=cmd_report)

    # run-perstep
    p_perstep = subparsers.add_parser(
        "run-perstep",
        help=(
            "Run per-step hi-pipeline eval with trace=True. "
            "Measures accuracy at each of 4 pipeline stages: "
            "Step A (Qwen hi→ru), Retrieval, Generation (GigaChat), Step B (Qwen ru→hi)."
        ),
    )
    p_perstep.add_argument("--golden-set-hi", help="Path to golden_set_hi.yaml (default: auto)")
    p_perstep.add_argument("--golden-set-ru", help="Path to golden_set.yaml (default: auto)")
    p_perstep.add_argument(
        "--prod-url",
        required=True,
        help="Prod base URL, e.g. http://localhost:8080",
    )
    p_perstep.add_argument("--demo-password", help="Demo user password to obtain JWT")
    p_perstep.add_argument("--jwt-token", help="JWT token (alternative to --demo-password)")
    p_perstep.add_argument("--run-dir", help="Output run directory (default: auto timestamped)")
    p_perstep.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip Ragas/sacrebleu metrics computation (save raw data only)",
    )
    p_perstep.set_defaults(func=cmd_run_perstep)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
