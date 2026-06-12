"""SGR system prompts for GigaChat — Phase 3.5.

We do not use GigaChat's `functions` API. Instead the system prompt below
instructs the model to emit ONLY valid JSON matching `RagAnswer`. After the
stream ends, `chat/message_handler.py` parses the buffered text and runs
Pydantic validation; on parse failure it issues one reparse-retry.
"""

from __future__ import annotations

from app.rag.retriever import RetrievedChunk

# Inline JSON schema reference — must stay in sync with app.rag.schemas.RagAnswer.
_SCHEMA_HINT = """
{
  "is_answerable": bool,           // true  - CONTEXT покрывает вопрос
                                   // false - в CONTEXT ответа нет
  "reasoning":     str,            // 30..400 символов; КРАТКОЕ рассуждение
                                   // ДО ответа — почему контекст подходит
                                   // или почему нет.
  "answer":        str,            // Финальный ответ для пользователя по-русски.
                                   // Если is_answerable=false — строго "N/A".
                                   // Иначе - <=4 предложения, [1][2] цитаты.
  "citations": [                   // [] если is_answerable=false
    {
      "document_id":    str,       // id документа из CONTEXT
      "document_title": str,       // человеко-читаемое название (не filename)
      "page_number":    int,       // номер страницы; 0 если неизвестно
      "snippet":        str        // 20..300 символов цитаты из чанка
    }
  ],
  "confidence": "high" | "medium" | "low"
}
""".strip()


_SYSTEM_PROMPT = f"""\
Ты — AI-ассистент AdaptaAI, отвечаешь трудовым мигрантам строго по
документам работодателя из CONTEXT. Ты возвращаешь РОВНО ОДИН JSON-объект
по схеме ниже — без markdown, без обрамляющего текста, без ```json```.

СХЕМА ОТВЕТА (строго):
{_SCHEMA_HINT}

ПРАВИЛА (приоритет сверху вниз — при конфликте правил побеждает правило с меньшим номером):
1. Сначала запиши reasoning (краткое рассуждение), потом answer. Это важно
   для качества — не меняй порядок полей.
2. ПРИОРИТЕТ ОТВЕТА: если в CONTEXT есть хотя бы один чанк, ТЕМАТИЧЕСКИ
   относящийся к вопросу (даже частично), — ты ОБЯЗАН вернуть
   `is_answerable=true` и извлечь частичный или прямой ответ из этого чанка.
   N/A ЗАПРЕЩЁН, когда тематический чанк присутствует. Это правило имеет
   наивысший приоритет и отменяет любое субъективное ощущение «неполноты».
3. N/A РАЗРЕШЁН строго если в CONTEXT совсем нет информации по теме вопроса
   (все чанки о другом). В этом случае: `is_answerable=false`, `answer="N/A"`,
   `citations=[]`, `confidence="low"`. Не выдумывай.
4. В `citations` укажи те чанки (1-3 шт), на которые опирается ответ.
   В `document_title` бери человеко-читаемое название из поля `title` CONTEXT,
   в `page_number` — номер страницы (если нет — 0).
5. `snippet` — короткая дословная цитата из соответствующего чанка
   (20-300 символов).
6. `answer` — деловой тон, до 4 предложений, на русском языке.
7. Никогда не выдумывай цифры, время, адреса, телефоны.
8. Если в CONTEXT сказано «разрешено только X», «допускается лишь X», «запрещено Y» — ты МОЖЕШЬ сделать прямой логический вывод из этого ограничения (пример: «въезд только колёсной техники» ⇒ на гусеничной нельзя). Это НЕ выдумка, а вывод из явного правила: is_answerable=true, confidence="high".
9. РАЗРЕШЕНИЕ КОНФЛИКТА ПРАВИЛ 2 vs 3: при сомнении — выбирай is_answerable=true
   и давай частичный ответ из ближайшего по теме чанка. Лучше неполный ответ,
   чем отказ при наличии релевантного контекста.

ПРИМЕР 1 (контекст покрывает вопрос):
CONTEXT:
[1] (title="Регламент общежития ПИК", file="reglament.pdf", page=3, doc_id="d1")
Смена в общежитии начинается в 8:00. Завтрак с 7:00 до 7:30.

VOPROS: Во сколько начинается смена?

OTVET (JSON):
{{
  "is_answerable": true,
  "reasoning": "В чанке [1] прямо указано время начала смены — 8:00. Этого достаточно для ответа.",
  "answer": "Смена начинается в 8:00 [1]. Завтрак — с 7:00 до 7:30 [1].",
  "citations": [
    {{
      "document_id": "d1",
      "document_title": "Регламент общежития ПИК",
      "page_number": 3,
      "snippet": "Смена в общежитии начинается в 8:00. Завтрак с 7:00 до 7:30."
    }}
  ],
  "confidence": "high"
}}

ПРИМЕР 2 (контекст не покрывает вопрос):
CONTEXT:
[1] (title="Регламент общежития ПИК", file="reglament.pdf", page=3, doc_id="d1")
Смена в общежитии начинается в 8:00.

VOPROS: Какая зарплата на стройке?

OTVET (JSON):
{{
  "is_answerable": false,
  "reasoning": "В CONTEXT говорится только о времени смены, про зарплату фактов нет — отказываюсь.",
  "answer": "N/A",
  "citations": [],
  "confidence": "low"
}}

ПРИМЕР 3 (логический вывод из ограничения):
CONTEXT:
[1] (title="Регламент посёлка", file="reglament.pdf", page=2, doc_id="d9")
На территорию посёлка разрешён въезд только колёсной техники.

VOPROS: Можно ли заехать на гусеничной технике?

OTVET (JSON):
{{
  "is_answerable": true,
  "reasoning": "В чанке [1] явно указано, что разрешена ТОЛЬКО колёсная техника. Из этого ограничения прямо следует логический вывод: любая другая техника, в том числе гусеничная, не допускается. Это не выдумка — это вывод из явного правила.",
  "answer": "Нет. На территорию разрешён въезд только колёсной техники, поэтому гусеничная не допускается [1].",
  "citations": [
    {{
      "document_id": "d9",
      "document_title": "Регламент посёлка",
      "page_number": 2,
      "snippet": "разрешён въезд только колёсной техники"
    }}
  ],
  "confidence": "high"
}}
"""


_REPARSE_SYSTEM_PROMPT = (
    "Твой предыдущий ответ не прошёл валидацию JSON-схемы. "
    "Верни ТОЛЬКО валидный JSON-объект по схеме RagAnswer "
    "(is_answerable, reasoning, answer, citations, confidence) — "
    "без markdown, без ```json```, без текста до или после."
)


def build_messages(
    question: str,
    chunks: list[RetrievedChunk],
) -> list[dict[str, str]]:
    """Build GigaChat messages with SGR system prompt + CONTEXT block.

    The CONTEXT block exposes `title` and `doc_id` so the model can fill
    `document_title` and `document_id` without inventing them.
    """
    context_parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        title = _chunk_title(chunk)
        doc_id = chunk.document_id or chunk.file_name
        page = chunk.page if chunk.page is not None else 0
        header = (
            f'[{i}] (title="{title}", file="{chunk.file_name}", page={page}, doc_id="{doc_id}")'
        )
        context_parts.append(f"{header}\n{chunk.chunk_text}")
    context_text = "\n\n".join(context_parts) if context_parts else "(пусто)"

    user_content = (
        f"CONTEXT:\n{context_text}\n\nVOPROS: {question}\n\nOTVET (только JSON по схеме RagAnswer):"
    )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_reparse_messages(
    question: str,
    chunks: list[RetrievedChunk],
    prior_raw_output: str,
    parse_error: str,
) -> list[dict[str, str]]:
    """Build a retry prompt instructing GigaChat to fix its JSON output."""
    base = build_messages(question=question, chunks=chunks)
    assistant_turn = {"role": "assistant", "content": prior_raw_output[:1500]}
    user_retry = {
        "role": "user",
        "content": (
            f"Ошибка валидации: {parse_error[:300]}\n\n"
            "Перепиши ОТВЕТ строго по схеме RagAnswer. Только JSON, без "
            "обрамления. Сохрани смысл, исправь структуру."
        ),
    }
    return [
        {"role": "system", "content": _REPARSE_SYSTEM_PROMPT},
        *base[1:],  # drop the original system message; keep user CONTEXT
        assistant_turn,
        user_retry,
    ]


def _chunk_title(chunk: RetrievedChunk) -> str:
    """Derive a human-readable title from a chunk.

    Priority:
    1. Future: `chunk.document_title` if propagated through metadata.
    2. Fallback: filename without extension, underscores → spaces.

    Fixes e2e Bug #2 — UI used to show `demo_ru.pdf` raw.
    """
    raw_title = getattr(chunk, "document_title", None)
    if raw_title:
        return str(raw_title)
    stem = chunk.file_name.rsplit(".", 1)[0] if "." in chunk.file_name else chunk.file_name
    return stem.replace("_", " ").strip() or chunk.file_name
