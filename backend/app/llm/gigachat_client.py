"""GigaChat client — Phase 3 LLM answer generation.

Uses GigaChat-2-Pro via httpx (raw HTTP) with OAuth token caching.
TLS via Russian CA bundle (GIGACHAT_CA_BUNDLE_PATH).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Read-timeout для SSE-стрима GigaChat. Default 30s исторически — но на длинном
# RAG-контексте (5-6 чанков) полный ответ часто требует 40-70 сек. Поднимаем
# дефолт до 90, оставляем override через env для eval-прогонов.
_GIGACHAT_READ_TIMEOUT_S = float(os.getenv("GIGACHAT_READ_TIMEOUT_S", "90"))


class GigaChatClient:
    """Async GigaChat client with OAuth token caching and SSE streaming."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at_ms: int = 0
        self._refresh_lock: asyncio.Lock = asyncio.Lock()
        self._settings = get_settings()
        # Last usage reported by GigaChat stream (populated after chat_stream completes).
        # GigaChat returns usage in the final SSE chunk at the top-level "usage" field
        # (not inside "delta").  If None after stream, message_handler falls back to
        # char/4 estimation.
        self.last_usage: dict[str, int] | None = None

    async def _fetch_token(self) -> tuple[str, int]:
        """Fetch a new OAuth access token from GigaChat OAuth endpoint.

        Returns (access_token, expires_at_ms).
        """
        settings = self._settings
        ca_bundle: str | None = getattr(settings, "gigachat_ca_bundle_path", None)
        verify: str | bool = ca_bundle if ca_bundle else False

        async with httpx.AsyncClient(verify=verify) as client:
            response = await client.post(
                settings.gigachat_oauth_url,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "RqUID": str(uuid.uuid4()),
                    "Authorization": f"Basic {settings.gigachat_authorization_key}",
                },
                data={"scope": settings.gigachat_scope},
                timeout=10.0,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            token: str = data["access_token"]
            expires_at_ms: int = int(data.get("expires_at", 0))
            return token, expires_at_ms

    async def _ensure_token(self) -> str:
        """Return cached token or refresh if expired (TTL - 2 min buffer)."""
        now_ms = int(time.time() * 1000)
        if self._token and now_ms < self._expires_at_ms - 120_000:
            return self._token
        async with self._refresh_lock:
            # Double-check after lock acquisition
            now_ms = int(time.time() * 1000)
            if self._token and now_ms < self._expires_at_ms - 120_000:
                return self._token
            self._token, self._expires_at_ms = await self._fetch_token()
            logger.info("GigaChat OAuth token refreshed")
            return self._token

    async def _raw_stream(
        self,
        messages: list[dict[str, str]],
        token: str,
    ) -> AsyncIterator[str]:
        """Make streaming HTTP request to GigaChat and yield content tokens.

        Also captures usage from the final SSE chunk (GigaChat emits it at the
        top-level "usage" key of the last non-[DONE] chunk).  Stored on
        self.last_usage so message_handler can read exact token counts after
        the stream completes.  If GigaChat does not emit usage, last_usage stays
        None and message_handler falls back to char/4 estimation.
        """
        settings = self._settings
        ca_bundle: str | None = getattr(settings, "gigachat_ca_bundle_path", None)
        verify: str | bool = ca_bundle if ca_bundle else False

        payload: dict[str, Any] = {
            "model": settings.gigachat_model,
            "messages": messages,
            "stream": True,
            "temperature": 0.0,  # детерминированный режим для стабильного is_answerable
            "max_tokens": 512,
            "top_p": 0.9,
        }

        async with httpx.AsyncClient(verify=verify) as client:
            async with client.stream(
                "POST",
                f"{settings.gigachat_base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "Authorization": f"Bearer {token}",
                },
                json=payload,
                timeout=httpx.Timeout(connect=5.0, read=_GIGACHAT_READ_TIMEOUT_S, write=5.0, pool=5.0),
            ) as response:
                if response.status_code == 401:
                    raise httpx.HTTPStatusError(
                        "401 Unauthorized",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line.removeprefix("data:").strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    # Capture top-level usage if present (GigaChat emits it on
                    # the final content chunk before [DONE]).
                    raw_usage = chunk.get("usage")
                    if raw_usage and isinstance(raw_usage, dict):
                        self.last_usage = {
                            "prompt_tokens": int(raw_usage.get("prompt_tokens", 0)),
                            "completion_tokens": int(raw_usage.get("completion_tokens", 0)),
                        }
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content: str | None = delta.get("content")
                    if content:
                        yield content

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """Stream GigaChat completion tokens as an async generator.

        Yields str tokens. Handles 401 with one token refresh + retry.
        """
        token = await self._ensure_token()
        try:
            async for tok in self._raw_stream(messages, token):
                yield tok
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                logger.warning("GigaChat 401 — refreshing token and retrying")
                self._token = None  # invalidate cache
                token = await self._ensure_token()
                async for tok in self._raw_stream(messages, token):
                    yield tok
            else:
                raise
