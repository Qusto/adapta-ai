"""Chat message handler — Phase 3 + Phase 3.5 SGR orchestration.

Pipeline (per language):

  ru-path:
    retrieve → GigaChat (SGR stream) → parse JSON → [reparse if fail] →
    emit answer/citations/meta SSE events → persist

  hi-path:
    Qwen hi→ru → retrieve → GigaChat (SGR stream) → parse JSON →
    Qwen ru→hi on `answer` field only → persist (citations stay RU)

SSE event types:
  * message_started — start of stream (UUIDs for user + agent messages)
  * token           — raw GigaChat tokens as they arrive (incremental UX)
  * answer          — final parsed answer text (post-translation if hi)
  * citations       — list with legacy field names for backwards compat
  * meta            — {is_answerable, reasoning, confidence}
  * done            — terminal event with latency + escalate flag
  * error           — non-terminal error (LLM_TIMEOUT, TRANSLATE_FAILED, …)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

import app.database as _db_module
from app.chat.sse_streamer import sse_event
from app.config import get_settings
from app.db.models import AiMessage
from app.llm.fallback import CANNED_RU_TIMEOUT
from app.chat.router import (
    DIRECT_INTENTS,
    classify,
    direct_answer,
    no_info_answer,
    rag_score_gate,
)
from app.llm.gigachat_client import GigaChatClient
from app.llm.qwen_client import QwenClient
from app.rag.answer_parser import SAFE_FALLBACK_ANSWER, ParseFailure, parse_rag_answer
from app.rag.factory import get_embedder, get_store
from app.rag.prompts import build_messages, build_reparse_messages
from app.rag.retriever import RetrievedChunk, Retriever
from app.rag.schemas import RagAnswer
from app.rag.store import PARTNER_PRODUCTS_COLLECTION, get_partner_products_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Emergency-detection constants (short-circuit path)
# ---------------------------------------------------------------------------

EMERGENCY_KEYWORDS_RU: list[str] = [
    "авария", "травма", "травмир", "вызовите скорую", "скорая помощь",
    "112", "103", "911",
    "помогите", "помоги пожалуйста", "сос ", " sos",
    "задыхаюсь", "теряю сознание", "потерял сознание",
    "кровь идёт", "кровотечение",
    "упал с", "сломал ногу", "сломал руку", "сломал",
    "пожар", "горит",
    "электротравма", "удар током",
    "умирает", "умер",
]
EMERGENCY_KEYWORDS_HI: list[str] = [
    "दुर्घटना", "चोट", "एम्बुलेंस", "112", "मदद करो", "खून बह रहा है",
    "बेहोश", "गिर गया", "टूट गया", "आग",
]

EMERGENCY_RESPONSE_RU = (
    "⚠️ Это похоже на экстренную ситуацию. Я уже уведомил HR — с вами свяжутся. "
    "Если есть угроза жизни, немедленно звоните 112. "
    "Не покидайте место происшествия, если безопасно."
)
EMERGENCY_RESPONSE_HI = (
    "⚠️ यह आपातकालीन स्थिति लगती है। मैंने HR को सूचित कर दिया है — वे आपसे संपर्क करेंगे। "
    "जीवन के लिए खतरा हो तो तुरंत 112 पर कॉल करें। यदि सुरक्षित हो तो घटनास्थल न छोड़ें।"
)


# ---------------------------------------------------------------------------
# Script-detection helper (Task 4: defence-in-depth)
# ---------------------------------------------------------------------------

# Деванагари: U+0900–U+097F
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def _detect_script_language(text: str, language: str) -> str:
    """Авто-коррекция language на основе скрипта текста.

    Если запрос содержит символы деванагари — принудительно считаем язык "hi",
    независимо от присланного тега (фронт иногда передаёт неверный).
    Остальные языки не трогаем.
    """
    if _DEVANAGARI_RE.search(text):
        if language != "hi":
            logger.info(
                "script_detect: Devanagari chars found in text, overriding language=%r → 'hi'",
                language,
            )
        return "hi"
    return language


def _is_emergency(text: str, lang: str) -> bool:
    """Return True if the text contains emergency keywords.

    Conservative: only return True when a clearly life-threatening phrase
    is present. False positives are worse than false negatives (cry-wolf).
    For HI questions both HI and RU keyword lists are checked (code-switching).
    """
    text_lc = text.lower().strip()
    if lang == "hi":
        keywords = EMERGENCY_KEYWORDS_HI + EMERGENCY_KEYWORDS_RU
    else:
        keywords = EMERGENCY_KEYWORDS_RU
    return any(kw in text_lc for kw in keywords)


# ---------------------------------------------------------------------------
# DMS fallback URL for partner_products chunks that have no url in metadata
# ---------------------------------------------------------------------------

_DMS_FALLBACK_URL = "https://sberbank.ru/dms-migrant"


# ---------------------------------------------------------------------------
# Product card builder (Task 3 — dual-RAG)
# ---------------------------------------------------------------------------


def _build_product_card(chunk: RetrievedChunk) -> dict[str, str] | None:
    """Build a product_card payload from a partner_products chunk.

    Reads product metadata from chunk attributes set by _dual_retrieve.
    Attributes are populated from ChromaDB metadata fields (set by seed script
    from frontmatter: product_title, product_subtitle, product_badge, product_url).
    Legacy field names (title, subtitle, badge, url) are also supported.

    Returns None if the chunk is not from partner_products.
    """
    if chunk.company_id != PARTNER_PRODUCTS_COLLECTION:
        return None

    # Prefer new frontmatter-sourced fields; fall back to legacy field names.
    title: str = (
        getattr(chunk, "product_title", "") or getattr(chunk, "title", "") or ""
    )
    subtitle: str = (
        getattr(chunk, "product_subtitle", "") or getattr(chunk, "subtitle", "") or ""
    )
    url: str = (
        getattr(chunk, "product_url", "") or getattr(chunk, "url", "") or ""
    )
    badge: str = (
        getattr(chunk, "product_badge", "") or getattr(chunk, "badge", "") or ""
    )

    if not title:
        stem = chunk.file_name.rsplit(".", 1)[0] if "." in chunk.file_name else chunk.file_name
        title = stem.replace("_", " ").strip() or chunk.file_name

    if not url:
        url = _DMS_FALLBACK_URL

    return {"title": title, "subtitle": subtitle, "url": url, "badge": badge}


# ---------------------------------------------------------------------------
# Dual-RAG retrieval helper
# ---------------------------------------------------------------------------


def _dual_retrieve(
    ru_question: str,
    company_id: str,
    top_employer: int = 3,
    top_sber: int = 3,
    final_top: int = 5,
) -> list[RetrievedChunk]:
    """Retrieve from employer_docs + partner_products and merge top-N by score.

    Uses Retriever for the employer-docs side so that unit tests can patch
    `app.chat.message_handler.Retriever` and inject mock search results.
    """
    # Employer side — use Retriever so existing test patches still work.
    retriever = Retriever(store=get_store(), embedder=get_embedder())
    employer_chunks: list[RetrievedChunk] = retriever.search(
        ru_question,
        company_id,
        top_k=top_employer,
    )

    # Partner-products side — query directly (no company_id filter).
    embedder = get_embedder()
    query_embedding: list[float] = embedder.embed_query(ru_question)
    partner_store = get_partner_products_store()
    sber_results: list[dict[str, Any]] = partner_store.query(
        query_embedding=query_embedding,
        n_results=top_sber,
    )

    sber_chunks: list[RetrievedChunk] = []
    for item in sber_results:
        chunk = RetrievedChunk(
            chunk_text=item.get("chunk_text", ""),
            score=float(item.get("score", 0.0)),
            file_name=item.get("file_name", ""),
            chunk_idx=int(item.get("chunk_idx", 0)),
            page=item.get("page"),
            company_id=PARTNER_PRODUCTS_COLLECTION,
            language=item.get("language", "ru"),
            document_id=item.get("document_id"),
        )
        # Attach product metadata from frontmatter fields (new) and legacy fields.
        chunk.product_title = item.get("product_title", "")  # type: ignore[attr-defined]
        chunk.product_subtitle = item.get("product_subtitle", "")  # type: ignore[attr-defined]
        chunk.product_url = item.get("product_url", "")  # type: ignore[attr-defined]
        chunk.product_badge = item.get("product_badge", "")  # type: ignore[attr-defined]
        # Legacy fallback names (also stored by seed script for backwards compat)
        chunk.title = item.get("title", "")  # type: ignore[attr-defined]
        chunk.subtitle = item.get("subtitle", "")  # type: ignore[attr-defined]
        chunk.url = item.get("url", "")  # type: ignore[attr-defined]
        chunk.badge = item.get("badge", "")  # type: ignore[attr-defined]
        sber_chunks.append(chunk)

    all_chunks = employer_chunks + sber_chunks
    all_chunks.sort(key=lambda c: c.score, reverse=True)
    return all_chunks[:final_top]


# ---------------------------------------------------------------------------
# Confidence mapping (Literal → float for legacy SSE/persistence layers)
# ---------------------------------------------------------------------------

_CONFIDENCE_FLOAT: dict[str, float] = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.3,
}


def _confidence_to_float(answer: RagAnswer, retrieval_top1: float) -> float:
    """Blend LLM self-rated confidence with retrieval top-1 score.

    We multiply the two so a hallucinated 'high' on weak retrieval still
    surfaces as a moderate number, but a real 'high' on strong retrieval
    stays close to top-1.
    """
    llm_conf = _CONFIDENCE_FLOAT.get(answer.confidence, 0.3)
    # Cap by retrieval strength so we never claim higher confidence than the
    # underlying evidence supports.
    return round(min(llm_conf, max(retrieval_top1, 0.1)), 3)


# ---------------------------------------------------------------------------
# Citation shaping
# ---------------------------------------------------------------------------


def _legacy_citations(
    answer: RagAnswer,
    retrieved: list[RetrievedChunk],
) -> list[dict[str, Any]]:
    """Build the legacy `citations` payload (SSE + DB column).

    Field names match the existing PRD §6.7 contract:
      [document_id, document_name, chunk_index, snippet, rank]

    `document_name` is now the **human-readable title** (Bug #2 fix), not
    the raw filename. We cross-reference retrieved chunks by document_id
    to recover `chunk_index` and `page` where possible.
    """
    chunks_by_doc: dict[str, RetrievedChunk] = {}
    for c in retrieved:
        key = c.document_id or c.file_name
        chunks_by_doc.setdefault(key, c)

    result: list[dict[str, Any]] = []
    for rank, cit in enumerate(answer.citations, start=1):
        retrieved_chunk = chunks_by_doc.get(cit.document_id)
        chunk_index = retrieved_chunk.chunk_idx if retrieved_chunk else 0
        result.append(
            {
                "document_id": cit.document_id,
                "document_name": cit.document_title,
                "chunk_index": chunk_index,
                "snippet": cit.snippet,
                "rank": rank,
            }
        )

    # If LLM returned is_answerable=True but no citations (rare), surface
    # the top retrieved chunk so the UI still has something to render.
    if not result and retrieved and answer.is_answerable:
        top = retrieved[0]
        result.append(
            {
                "document_id": top.document_id or top.file_name,
                "document_name": _fallback_title(top),
                "chunk_index": top.chunk_idx,
                "snippet": top.chunk_text[:200],
                "rank": 1,
            }
        )
    return result


def _fallback_title(chunk: RetrievedChunk) -> str:
    """Filename → human-friendly title (Bug #2 fix at the SSE boundary)."""
    raw = getattr(chunk, "document_title", None)
    if raw:
        return str(raw)
    stem = chunk.file_name.rsplit(".", 1)[0] if "." in chunk.file_name else chunk.file_name
    return stem.replace("_", " ").strip() or chunk.file_name


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _persist_messages(
    user_id: uuid.UUID,
    language: str,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
    confidence: float,
    latency_ms: int,
    is_answerable: bool | None = None,
    confidence_label: str | None = None,
    escalate: bool = False,
    is_emergency: bool = False,
) -> None:
    """Persist user + agent ai_messages rows. Errors are swallowed.

    Saves `is_answerable` and inferred float confidence on the user-message
    row (Variant 1) so the HR-escalations endpoint can query user messages
    directly without joining to the following agent message.
    `escalate=True` marks any HR-visible message (out-of-corpus OR emergency).
    `is_emergency=True` marks only true keyword-emergency messages, so
    _severity() can gate critical/emergency on is_emergency exclusively.
    """
    # Derive confidence float for the user-message row from the label.
    user_confidence: float | None = _CONFIDENCE_FLOAT.get(confidence_label or "", None)
    try:
        async with _db_module.async_session_factory() as session:
            user_msg = AiMessage(
                user_id=user_id,
                role="user",
                text=question,
                citations=None,
                language=language,
                confidence=user_confidence,
                is_answerable=is_answerable,
                latency_ms=None,
                escalate=escalate,
                is_emergency=is_emergency,
            )
            agent_msg = AiMessage(
                user_id=user_id,
                role="agent",
                text=answer,
                citations=citations,
                language=language,
                confidence=confidence,
                is_answerable=is_answerable,
                latency_ms=latency_ms,
                escalate=escalate,
                is_emergency=is_emergency,
            )
            session.add(user_msg)
            session.add(agent_msg)
            await session.commit()
            logger.info("Persisted ai_messages for user_id=%s (user+agent)", user_id)
    except Exception as exc:
        logger.error("Failed to persist ai_messages: %s", exc)


# ---------------------------------------------------------------------------
# Main streaming pipeline
# ---------------------------------------------------------------------------


async def stream_chat_response(  # noqa: PLR0912, PLR0915
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    question: str,
    language: str,
    skip_translate_response: bool = False,
    trace: bool = False,
    pipeline_mode: str | None = None,
    qwen_model_override: str | None = None,
) -> AsyncIterator[str]:
    """Full SGR pipeline: retrieve → SGR LLM → validated answer → SSE.

    Deliberately a single async generator: SSE event emission, error branches
    and per-language steps must run in one cooperative coroutine so the
    StreamingResponse sees events in real-time. Splitting into sub-coroutines
    forces buffering. We accept the complexity warnings instead.
    """
    start_ms = int(time.time() * 1000)
    user_message_id = str(uuid.uuid4())
    agent_message_id = str(uuid.uuid4())

    yield sse_event(
        "message_started",
        {
            "user_message_id": user_message_id,
            "agent_message_id": agent_message_id,
        },
    )

    # ---- Script-detect: если текст содержит деванагари → language="hi" ----
    language = _detect_script_language(question, language)

    # ---- Emergency short-circuit (life-threatening situations skip RAG) ----
    if _is_emergency(question, language):
        logger.warning(
            "Emergency detected for user_id=%s lang=%s — short-circuit activated",
            user_id,
            language,
        )
        canned = EMERGENCY_RESPONSE_HI if language == "hi" else EMERGENCY_RESPONSE_RU
        latency_ms_emergency = int(time.time() * 1000) - start_ms
        yield sse_event("emergency", {"severity": "critical", "lang": language})
        yield sse_event("answer", {"text": canned, "is_final": True})
        yield sse_event(
            "done",
            {
                "agent_message_id": agent_message_id,
                "confidence": 1.0,
                "latency_ms": latency_ms_emergency,
                "escalate": True,
                "is_emergency": True,
                "severity": "critical",
                "is_answerable": True,
                "citations": [],
            },
        )
        await _persist_messages(
            user_id=user_id,
            language=language,
            question=question,
            answer=canned,
            citations=[],
            confidence=1.0,
            latency_ms=latency_ms_emergency,
            is_answerable=True,
            confidence_label=None,
            escalate=True,
            is_emergency=True,
        )
        return

    # ---- Intent router (WS-F, variant D): answer obvious non-questions
    # directly in the user's language, skip RAG + product card. Bias-to-RAG:
    # only clearly non-domain input (greeting/thanks/test/gibberish) is caught;
    # anything substantive falls through to the RAG pipeline below. ----
    intent = classify(question)
    if intent in DIRECT_INTENTS:
        logger.info("Router: intent=%s lang=%s → direct answer (no RAG)", intent, language)
        direct = direct_answer(intent, language)
        latency_ms_direct = int(time.time() * 1000) - start_ms
        yield sse_event("answer", {"text": direct, "is_final": True})
        yield sse_event(
            "done",
            {
                "agent_message_id": agent_message_id,
                "confidence": 1.0,
                "latency_ms": latency_ms_direct,
                "escalate": False,
                "is_answerable": True,
                "citations": [],
            },
        )
        await _persist_messages(
            user_id=user_id,
            language=language,
            question=question,
            answer=direct,
            citations=[],
            confidence=1.0,
            latency_ms=latency_ms_direct,
            is_answerable=True,
            confidence_label="high",
            escalate=False,
        )
        return

    gigachat = GigaChatClient()
    qwen = QwenClient()

    # ---- Ablation mode (read once, used throughout the pipeline) ----
    # Request-level pipeline_mode overrides the env setting; fall back to env, then "both".
    eval_mode: str = pipeline_mode or get_settings().eval_pipeline_mode or "both"
    # eval_mode: "both" | "qwen_only" | "gigachat_only"
    # In ablation modes (not "both") Steps A and B are always skipped.

    # ---- Step A: <lang>→ru (non-ru paths in "both" mode; corpus is Russian) ----
    # Для ru в режиме "both" — канонизация через Qwen (стабилизирует формулировку
    # перед retrieval и снижает вариативность GigaChat SGR).
    # Для hi/en — перевод через Qwen как прежде.
    # Ablation-режимы (не "both") — Step A пропускается.
    ru_question = question
    if language == "ru" and eval_mode == "both":
        try:
            canonicalize_result = await qwen.canonicalize_ru(question)
            ru_question = canonicalize_result.get("ru_query", question)
        except Exception as exc:
            logger.warning("Qwen canonicalize_ru failed: %s — using raw text", exc)
            ru_question = question
        if trace:
            yield sse_event(
                "meta",
                {"trace": {"step_a_canonicalize_ru_question": ru_question}},
            )
    elif language in ("hi", "en") and eval_mode == "both":
        try:
            if language == "hi":
                translate_result = await qwen.translate_hi_to_ru(question)
            else:
                translate_result = await qwen.translate_en_to_ru(question)
            ru_question = translate_result.get("ru_query", question)
        except Exception as exc:
            logger.warning("Qwen Step A (%s→ru) failed: %s — using raw text", language, exc)
            ru_question = question
        if trace:
            yield sse_event(
                "meta",
                {"trace": {"step_a_qwen_ru_question": ru_question}},
            )

    # ---- Dual-collection retrieval (employer_docs + partner_products) ----
    try:
        chunks: list[RetrievedChunk] = await asyncio.to_thread(
            _dual_retrieve,
            ru_question,
            str(company_id),
        )
    except Exception as exc:
        logger.error("Retrieval failed: %s", exc)
        yield sse_event("error", {"code": "RETRIEVAL_FAILED", "message": str(exc)})
        yield sse_event(
            "done",
            {
                "agent_message_id": agent_message_id,
                "confidence": 0.0,
                "latency_ms": int(time.time() * 1000) - start_ms,
                "escalate": False,
            },
        )
        return

    if trace:
        yield sse_event(
            "meta",
            {
                "trace": {
                    "retrieved_doc_ids": [
                        c.document_id or c.file_name for c in chunks
                    ],
                    "retrieved_chunks": [
                        {
                            "chunk_text": c.chunk_text,
                            "file_name": c.file_name,
                            "document_id": c.document_id,
                            "score": c.score,
                            "chunk_idx": c.chunk_idx,
                        }
                        for c in chunks
                    ],
                }
            },
        )

    retrieval_top1 = chunks[0].score if chunks else 0.0

    # ---- Retrieval-score gate (WS-F): is the question inside our corpus? ----
    # Domains are derived automatically from the uploaded employer documents via
    # embedding similarity. If the top employer-doc score is below the gate, the
    # question is outside what we know — answer gracefully + escalate to HR
    # instead of forcing the LLM to hallucinate a "not found / 0%" reply.
    employer_scores = [
        c.score for c in chunks if c.company_id != PARTNER_PRODUCTS_COLLECTION
    ]
    employer_top1 = max(employer_scores) if employer_scores else 0.0
    sber_scores = [
        c.score for c in chunks if c.company_id == PARTNER_PRODUCTS_COLLECTION
    ]
    sber_top1 = max(sber_scores) if sber_scores else 0.0

    gate = rag_score_gate()
    soft_floor = gate - 0.065  # grey band: [soft_floor, gate) → let LLM decide

    if employer_top1 >= gate:
        # In-corpus: normal LLM path (fall through below).
        logger.info(
            "Router: employer_top1=%.3f >= gate=%.3f sber_top1=%.3f → in-corpus, proceed to LLM",
            employer_top1, gate, sber_top1,
        )
    elif employer_top1 >= soft_floor:
        # Grey zone: borderline score — do NOT early-return; let LLM + is_answerable decide.
        logger.info(
            "Router: employer_top1=%.3f in grey zone [%.3f, %.3f) sber_top1=%.3f → proceed to LLM",
            employer_top1, soft_floor, gate, sber_top1,
        )
    elif sber_top1 >= gate:
        # Sber product question: relevant Sber chunk present — proceed to LLM for product card.
        logger.info(
            "Router: employer_top1=%.3f < soft_floor=%.3f but sber_top1=%.3f >= gate=%.3f → Sber product path",
            employer_top1, soft_floor, sber_top1, gate,
        )
    else:
        # Truly out-of-corpus: graceful fallback + HR ticket, but NOT emergency.
        # out-of-corpus → escalate=True (передано HR), но is_emergency=False →
        # severity high/unanswerable, НЕ emergency.
        logger.info(
            "Router: employer_top1=%.3f < soft_floor=%.3f sber_top1=%.3f < gate=%.3f → out-of-corpus, graceful fallback",
            employer_top1, soft_floor, sber_top1, gate,
        )
        fallback = no_info_answer(language)
        latency_ms_gate = int(time.time() * 1000) - start_ms
        yield sse_event("answer", {"text": fallback, "is_final": True})
        yield sse_event("citations", {"citations": []})
        yield sse_event(
            "meta",
            {"is_answerable": False, "reasoning": "router:out_of_corpus", "confidence": "low"},
        )
        yield sse_event("product_card", {"product_card": None})
        yield sse_event(
            "done",
            {
                "agent_message_id": agent_message_id,
                "confidence": round(employer_top1, 3),
                "latency_ms": latency_ms_gate,
                "escalate": True,
                "is_emergency": False,
                "is_answerable": False,
                "citations": [],
            },
        )
        await _persist_messages(
            user_id=user_id,
            language=language,
            question=question,
            answer=fallback,
            citations=[],
            confidence=round(employer_top1, 3),
            latency_ms=latency_ms_gate,
            is_answerable=False,
            confidence_label="low",
            escalate=True,
            is_emergency=False,
        )
        return

    messages = build_messages(question=ru_question, chunks=chunks)

    # ---- LLM generation: branch by eval_mode ----
    # "both" (default) — GigaChat streaming exactly as before.
    # "qwen_only"      — Qwen non-streaming; single token SSE event with full content.
    # "gigachat_only"  — GigaChat streaming as-is (Steps A/B already skipped above).
    #
    # Token accounting:
    #   GigaChat: captured from top-level "usage" field in last SSE chunk
    #             (stored in gigachat.last_usage after stream ends).
    #             If GigaChat does not emit usage (common in stream mode), we fall
    #             back to char/4 estimation.
    #             # token estimate method: char/4 (≈ GPT-style tokenisation avg)
    #   Qwen:     exact values from response.usage via OpenRouter (always present).

    raw_buffer_parts: list[str] = []
    llm_timeout = False
    llm_error_code: str = "LLM_TIMEOUT"
    llm_error_message: str = "LLM request timed out"
    # Token usage populated after generation block.
    prompt_tokens: int = 0
    completion_tokens: int = 0
    generator_name: str = "gigachat"

    if eval_mode == "qwen_only":
        # ---- Qwen non-streaming generation ----
        # generator_name = real model slug so eval pricing matches the correct tier.
        _effective_qwen_model = qwen_model_override or qwen._settings.qwen_model
        generator_name = _effective_qwen_model  # e.g. "qwen/qwen3-235b-a22b"
        try:
            qwen_content, qwen_usage = await qwen.generate_answer(
                messages, model=qwen_model_override
            )
            raw_buffer_parts.append(qwen_content)
            prompt_tokens = qwen_usage["prompt_tokens"]
            completion_tokens = qwen_usage["completion_tokens"]
            # One synthetic token event so legacy SSE consumers see something.
            yield sse_event("token", {"text": qwen_content})
        except Exception as exc:
            llm_timeout = True
            llm_error_code = "LLM_ERROR"
            llm_error_message = f"Qwen generate_answer failed: {type(exc).__name__}"
            logger.error("Qwen generate_answer error: %s", exc)
    else:
        # ---- GigaChat SGR stream (both / gigachat_only) ----
        gigachat.last_usage = None  # reset before stream
        try:
            async for token in gigachat.chat_stream(messages=messages):
                raw_buffer_parts.append(token)
                # Stream raw tokens so the client UI still feels alive. The frontend
                # is free to ignore `token` events and read `answer` at the end —
                # but legacy clients (and our incremental-streaming tests) need them.
                yield sse_event("token", {"text": token})
        except TimeoutError:
            llm_timeout = True
            llm_error_code = "LLM_TIMEOUT"
            llm_error_message = "LLM не ответил в отведённое время"
            logger.warning("GigaChat asyncio.TimeoutError")
        except httpx.HTTPStatusError as exc:
            # Различаем 402/403/429/5xx — admin должен видеть причину, не «таймаут»
            status = exc.response.status_code if exc.response else 0
            llm_timeout = True
            if status == 402:
                llm_error_code = "LLM_BILLING_REQUIRED"
                llm_error_message = "GigaChat: оплата требуется (402). Пополнить баланс в Sber-AI-кабинете."
            elif status == 403:
                llm_error_code = "LLM_QUOTA_EXCEEDED"
                llm_error_message = "GigaChat: ключ превысил квоту (403). Запросить увеличение или новый ключ."
            elif status == 429:
                llm_error_code = "LLM_RATE_LIMITED"
                llm_error_message = "GigaChat: rate limit (429). Снизить частоту запросов."
            elif 500 <= status < 600:
                llm_error_code = "LLM_PROVIDER_DOWN"
                llm_error_message = f"GigaChat: серверная ошибка ({status}). Временный сбой провайдера."
            else:
                llm_error_code = "LLM_HTTP_ERROR"
                llm_error_message = f"GigaChat: HTTP {status}"
            logger.error("GigaChat HTTP %s: %s", status, exc)
        except httpx.HTTPError as exc:
            llm_timeout = True
            llm_error_code = "LLM_NETWORK_ERROR"
            llm_error_message = f"GigaChat: сетевая ошибка ({type(exc).__name__})"
            logger.error("GigaChat network error: %s", exc)
        except Exception as exc:
            llm_timeout = True
            llm_error_code = "LLM_ERROR"
            llm_error_message = f"GigaChat: неожиданная ошибка ({type(exc).__name__})"
            logger.error("GigaChat stream error: %s", exc)

        # Collect GigaChat token usage (exact if provider emitted it, else estimate).
        if gigachat.last_usage is not None:
            prompt_tokens = gigachat.last_usage["prompt_tokens"]
            completion_tokens = gigachat.last_usage["completion_tokens"]
        else:
            # GigaChat did not emit usage in stream — fall back to char/4 estimate.
            # token estimate method: char/4 (≈ GPT-style tokenisation avg)
            raw_so_far = "".join(raw_buffer_parts)
            prompt_chars = sum(len(m.get("content", "")) for m in messages)
            prompt_tokens = max(1, prompt_chars // 4)
            completion_tokens = max(1, len(raw_so_far) // 4)

    if llm_timeout:
        yield sse_event("error", {"code": llm_error_code, "message": llm_error_message})
        yield sse_event("token", {"text": CANNED_RU_TIMEOUT})
        final_answer_text = CANNED_RU_TIMEOUT
        parsed: RagAnswer = RagAnswer(
            is_answerable=False,
            reasoning=(
                "LLM не ответил в отведённое время. Возвращаю безопасный "
                "fallback с предложением обратиться к HR."
            ),
            answer=CANNED_RU_TIMEOUT,
            citations=[],
            confidence="low",
        )
        legacy_citations: list[dict[str, Any]] = []
        confidence_float = 0.0
    else:
        raw_buffer = "".join(raw_buffer_parts)
        parsed_or_fail = parse_rag_answer(raw_buffer)

        # ---- Reparser retry (one shot) ----
        if isinstance(parsed_or_fail, ParseFailure):
            logger.warning(
                "SGR parse failed, attempting reparser retry. error=%s",
                parsed_or_fail.error[:120],
            )
            reparse_msgs = build_reparse_messages(
                question=ru_question,
                chunks=chunks,
                prior_raw_output=raw_buffer,
                parse_error=parsed_or_fail.error,
            )
            retry_parts: list[str] = []
            try:
                if eval_mode == "qwen_only":
                    # Reparse via Qwen in qwen_only mode.
                    retry_content, retry_usage = await qwen.generate_answer(
                        reparse_msgs, model=qwen_model_override
                    )
                    retry_parts.append(retry_content)
                    prompt_tokens += retry_usage["prompt_tokens"]
                    completion_tokens += retry_usage["completion_tokens"]
                else:
                    async for token in gigachat.chat_stream(messages=reparse_msgs):
                        retry_parts.append(token)
            except Exception as exc:
                logger.error("Reparser retry stream failed: %s", exc)
            retry_buffer = "".join(retry_parts)
            parsed_or_fail = parse_rag_answer(retry_buffer)

        # ---- Safe fallback after double-failure ----
        if isinstance(parsed_or_fail, ParseFailure):
            logger.error(
                "SGR parse failed twice — using safe fallback. error=%s",
                parsed_or_fail.error[:120],
            )
            yield sse_event(
                "error",
                {"code": "SGR_PARSE_FAILED", "message": parsed_or_fail.error[:200]},
            )
            parsed = SAFE_FALLBACK_ANSWER
        else:
            parsed = parsed_or_fail

        # Replace only the LLM sentinel "N/A" with a user-friendly localised message.
        # Any other answer (including SAFE_FALLBACK_ANSWER "попробуйте...") is kept as-is.
        final_answer_text = no_info_answer(language) if parsed.answer == "N/A" else parsed.answer
        legacy_citations = _legacy_citations(parsed, chunks)
        confidence_float = (
            0.0 if not parsed.is_answerable else _confidence_to_float(parsed, retrieval_top1)
        )

    # ---- Trace: LLM ru answer (before Step B) ----
    if trace and language == "hi":
        yield sse_event(
            "meta",
            {"trace": {"gigachat_ru_answer": final_answer_text}},
        )

    # ---- Step B: ru→<lang> on the `answer` field only (citations stay RU) ----
    # Skipped when skip_translate_response=True OR in ablation modes (not "both").
    effective_language = language
    if (
        language in ("hi", "en")
        and eval_mode == "both"
        and not llm_timeout
        and parsed.is_answerable
        and not skip_translate_response
    ):
        try:
            if language == "hi":
                translated = await qwen.translate_ru_to_hi(final_answer_text)
            else:
                translated = await qwen.translate_ru_to_en(final_answer_text)
            final_answer_text = translated
            yield sse_event("token", {"text": translated})
            if trace:
                yield sse_event(
                    "meta",
                    {"trace": {"step_b_qwen_translated_answer": translated}},
                )
        except Exception as exc:
            logger.warning("Qwen Step B (ru→%s) failed: %s", language, exc)
            yield sse_event(
                "error",
                {
                    "code": "TRANSLATE_FAILED",
                    "message": "Translation failed. Showing Russian answer.",
                },
            )
    elif language in ("hi", "en") and eval_mode == "both" and skip_translate_response:
        # Step B was skipped; answer stays in Russian
        effective_language = "ru"
        logger.info("Step B skipped (skip_translate_response=True): answer stays in RU")
    elif language in ("hi", "en") and eval_mode != "both":
        # Ablation mode: no translation, answer stays as-is
        effective_language = "ru"
        logger.info("Step B skipped (eval_mode=%s): answer stays in source language", eval_mode)

    # ---- product_card: only when the top-1 chunk is a partner_product AND the
    # answer is actually relevant (is_answerable). Prevents an irrelevant promo
    # (e.g. СберЗдоровье) from appearing under a "not found / 0% confidence"
    # reply to off-topic input like "test".
    product_card: dict[str, str] | None = None
    if chunks and parsed.is_answerable:
        product_card = _build_product_card(chunks[0])

    # ---- SGR structured events ----
    yield sse_event("answer", {"text": final_answer_text})
    yield sse_event("citations", {"citations": legacy_citations})
    yield sse_event(
        "meta",
        {
            "is_answerable": parsed.is_answerable,
            "reasoning": parsed.reasoning,
            "confidence": parsed.confidence,
        },
    )
    yield sse_event("product_card", {"product_card": product_card})

    latency_ms = int(time.time() * 1000) - start_ms
    yield sse_event(
        "done",
        {
            "agent_message_id": agent_message_id,
            "confidence": confidence_float,
            "latency_ms": latency_ms,
            "escalate": False,
            "effective_language": effective_language,
            # Ablation eval token accounting (non-breaking additions).
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "generator": generator_name,
        },
    )

    await _persist_messages(
        user_id=user_id,
        language=language,
        question=question,
        answer=final_answer_text,
        citations=legacy_citations,
        confidence=confidence_float,
        latency_ms=latency_ms,
        is_answerable=parsed.is_answerable,
        confidence_label=parsed.confidence,
    )
