"""Prompt builder for GigaChat answer generation -- Phase 3.

Builds the RAG system+user prompt per PRD/06_RAG_DESIGN.md section 3.1.
Russian language strings are intentional (RUF001/RUF002 suppressed globally).
"""

from __future__ import annotations

from app.rag.retriever import RetrievedChunk

_SYSTEM_PROMPT = (
    "Ты - AI-ассистент AdaptaAI, который помогает трудовым мигрантам в России.\n"
    "Ты отвечаешь СТРОГО на основе предоставленного CONTEXT - фрагментов из официальных\n"
    "документов работодателя. Если ответа в CONTEXT нет, скажи честно:\n"
    "Ne nashyol v zagruzhennykh dokumentakh. Rekomenduyu zadat' etot vopros HR-spetsialistu.\n"
    "\n"
    "PRAVILA:\n"
    "1. Nikogda ne vydumyvay fakty, tsifry, vremya, adresa, telefony.\n"
    "2. Каждое утверждение помечай номером источника в квадратных скобках: [1], [2], [3].\n"
    "3. Отвечай кратко (< 4 предложения), деловым тоном.\n"
    "4. Отвечай на русском языке. (Перевод на хинди делает Qwen.)\n"
    "5. Если вопрос не про работу/проживание/документы - вежливо откажись."
)


def build_messages(
    question: str,
    chunks: list[RetrievedChunk],
) -> list[dict[str, str]]:
    """Build GigaChat messages list with RAG context.

    Args:
        question: User question (in Russian).
        chunks: Retrieved chunks from ChromaDB.

    Returns:
        List of {role, content} dicts for GigaChat API.
    """
    context_parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        page_info = f", str. {chunk.page}" if chunk.page is not None else ""
        context_parts.append(f"[{i}] (source: {chunk.file_name}{page_info}) {chunk.chunk_text}")
    context_text = "\n".join(context_parts)

    user_content = f"CONTEXT:\n{context_text}\n\nVOPROS: {question}\n\nOTVET:"

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
