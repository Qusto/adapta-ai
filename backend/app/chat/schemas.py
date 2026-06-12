"""Pydantic schemas for Phase 3 chat endpoint."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    """Request body for POST /api/v1/chat/messages."""

    text: str = Field(..., min_length=1, max_length=1000)
    language: Literal["ru", "hi", "en"] = "ru"
    skip_translate_response: bool = Field(
        default=False,
        description=(
            "When True and language='hi', skip Step B (Qwen ru→hi translation). "
            "The answer is returned in Russian. Useful for eval/debugging hi-pipeline."
        ),
    )
    trace: bool = Field(
        default=False,
        description=(
            "When True, emit additional SSE `event: meta` events with intermediate "
            "pipeline data: Step A translation, retrieved doc IDs/chunks, GigaChat "
            "answer before Step B, Step B translation. Used by per-step eval."
        ),
    )
    pipeline_mode: Literal["both", "qwen_only", "gigachat_only"] | None = Field(
        default=None,
        description=(
            "Override eval_pipeline_mode for this request only. "
            "'both' (default): full pipeline with Qwen Steps A/B and GigaChat SGR. "
            "'qwen_only': Qwen handles generation, Steps A/B skipped. "
            "'gigachat_only': GigaChat only, Steps A/B skipped. "
            "When None, the server-side EVAL_PIPELINE_MODE env setting is used."
        ),
    )
    qwen_model_override: str | None = Field(
        default=None,
        description=(
            "Override Qwen model slug for this request (e.g. 'qwen/qwen3-235b-a22b'). "
            "Applies only when pipeline_mode='qwen_only'. "
            "When None, the server-side QWEN_MODEL env setting is used."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_lang_alias(cls, data: Any) -> Any:
        """Accept `lang` as an alias for `language` (used by eval scripts)."""
        if isinstance(data, dict):
            if "lang" in data and "language" not in data:
                data = dict(data)
                data["language"] = data.pop("lang")
            elif "lang" in data:
                data = {k: v for k, v in data.items() if k != "lang"}
        return data
