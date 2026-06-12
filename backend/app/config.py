"""Application settings — Pydantic Settings reads env vars (or infra/.env).

Phase 0 minimum surface area: required env vars come from `ORCHESTRATION.md §6`.
Additional fields will be added in Phase 1+ (JWT TTLs, embeddings model path, etc.)
without breaking the existing public API.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve repo paths so we can locate infra/.env when running outside Docker.
_BACKEND_ROOT: Path = Path(__file__).resolve().parents[1]
_REPO_ROOT: Path = _BACKEND_ROOT.parent
_INFRA_ENV: Path = _REPO_ROOT / "infra" / ".env"


class Settings(BaseSettings):
    """Typed settings loaded from environment variables (or infra/.env)."""

    model_config = SettingsConfigDict(
        env_file=(str(_INFRA_ENV),) if _INFRA_ENV.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- GigaChat (answer LLM) ---------------------------------------------
    gigachat_authorization_key: str
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2-Pro"
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

    # --- OpenRouter / Qwen (translate LLM) ---------------------------------
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    qwen_model: str = "qwen/qwen-2.5-72b-instruct"

    # --- Database ----------------------------------------------------------
    database_url: str

    # --- Auth secrets ------------------------------------------------------
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    invite_secret: str

    # --- JWT TTLs (Phase 1) ------------------------------------------------
    jwt_ttl_hr_seconds: int = 28800
    jwt_ttl_migrant_seconds: int = 2592000
    invite_ttl_days: int = 7

    # --- SMTP / MailHog (Phase 1) ------------------------------------------
    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_from: str = "noreply@adapta.demo"
    invite_base_url: str = "http://localhost:8000/i"
    # Optional real-SMTP auth (Yandex / Gmail / etc.). Defaults preserve MailHog flow.
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_security: Literal["none", "tls", "starttls"] = "none"

    # --- ChromaDB (RAG vector store, Phase 2) ---------------------------------
    chroma_persist_path: str = "./data/chromadb"

    # --- File storage (RAG uploads, Phase 2) ----------------------------------
    uploads_path: str = "./data/uploads"

    # --- Postgres (compose) ------------------------------------------------
    postgres_db: str = "adapta"
    postgres_user: str = "adapta"
    postgres_password: str = "change-me-strong-string"

    # --- Demo docs password (Task 2) ---------------------------------------
    # Used by StaticAuthMiddleware and POST /docs/login to gate /docs/modules/site/*.
    # If not set, the docs gate returns 503.
    adapta_demo_password: str | None = None

    # --- Ablation experiment pipeline mode (eval only) ---------------------
    # Controls which LLM stack is used for RAG answer generation.
    # "both"          — default prod behaviour (Step A qwen→ru, GigaChat SGR, Step B ru→hi)
    # "qwen_only"     — skip Steps A+B; use Qwen for generation (no translation)
    # "gigachat_only" — skip Steps A+B; use GigaChat as-is (no translation)
    # Switch via env: EVAL_PIPELINE_MODE=qwen_only
    eval_pipeline_mode: Literal["both", "qwen_only", "gigachat_only"] = "both"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached Settings instance for application-wide use."""
    # Settings reads values from env / dotenv at runtime — mypy can't see that
    # so we suppress the call-arg complaint here, where the policy is enforced.
    return Settings()  # type: ignore[call-arg]
