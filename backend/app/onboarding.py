"""Phase 10 — canonical onboarding journey + personal documents.

Single source of truth for the migrant status model. The backend stores only
machine keys + status + dates on `User.onboarding_state` / `User.personal_documents`
(JSONB); the frontend maps keys → localized labels (RU/HI/EN/UZ).

Document storage is METADATA ONLY (number/expiry/status). Real document files
require at-rest encryption — deferred to v1.1.
"""

from __future__ import annotations

from typing import Any

# Canonical 8-step onboarding journey (order matters — same as HR worker-detail).
STEP_KEYS: list[str] = [
    "arrived",      # Приехал в РФ / Регистрация
    "snils",        # Получил СНИЛС
    "inn",          # Получил ИНН
    "biometrics",   # Сдал биометрию (МФЦ)
    "patent",       # Оформил патент (ММЦ Сахарово)
    "salary_card",  # Открыл зарплатную карту
    "partner_mobile",   # Подключил мобильный тариф партнёра
    "dms",          # Получил ДМС
]

# Base document set the migrant is expected to upload (required for progress bar).
DOC_TYPES: list[str] = [
    "passport",
    "migration_card",
    "registration",
    "patent",
    "snils",
    "inn",
    "dms",
]

# Uploading one of these documents auto-advances the matching onboarding step.
DOC_TO_STEP: dict[str, str] = {
    "snils": "snils",
    "inn": "inn",
    "patent": "patent",
    "dms": "dms",
}

STEP_TODO = "todo"
STEP_IN_PROGRESS = "in_progress"
STEP_DONE = "done"
_STEP_STATUSES = {STEP_TODO, STEP_IN_PROGRESS, STEP_DONE}

DOC_MISSING = "missing"
DOC_UPLOADED = "uploaded"
DOC_VALID = "valid"
DOC_EXPIRING = "expiring"
DOC_EXPIRED = "expired"


def default_onboarding(registered_at_iso: str | None = None) -> dict[str, Any]:
    """Fresh journey: step 1 (arrived) done at registration, the rest todo."""
    steps = []
    for key in STEP_KEYS:
        done = key == "arrived"
        steps.append(
            {
                "key": key,
                "status": STEP_DONE if done else STEP_TODO,
                "updated_at": registered_at_iso if done else None,
            }
        )
    return {"steps": steps}


def default_documents() -> dict[str, Any]:
    """Fresh base set: every required document missing (progress 0/N)."""
    return {
        "docs": [
            {
                "type": t,
                "status": DOC_MISSING,
                "number": None,
                "expires_at": None,
                "uploaded_at": None,
            }
            for t in DOC_TYPES
        ]
    }


def onboarding_progress(state: dict[str, Any]) -> tuple[int, int]:
    """Return (done_count, total)."""
    steps = state.get("steps", [])
    done = sum(1 for s in steps if s.get("status") == STEP_DONE)
    return done, len(STEP_KEYS)


def documents_progress(docs_state: dict[str, Any]) -> tuple[int, int]:
    """Return (uploaded_count, required_total)."""
    docs = docs_state.get("docs", [])
    uploaded = sum(1 for d in docs if d.get("status") != DOC_MISSING)
    return uploaded, len(DOC_TYPES)
