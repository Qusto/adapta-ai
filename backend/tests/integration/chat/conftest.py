"""Integration chat conftest — extends the parent integration conftest.

Adds TRUNCATE of ai_messages table (Phase 3) to the cleanup routine.
The parent conftest.py handles company/user/invite truncation.
This conftest patches the parent's teardown to also truncate ai_messages
once that table exists (added by migration 0003_ai_messages).
"""

from __future__ import annotations

# No additional fixtures needed at this scope — all fixtures come from
# tests/conftest.py (session) and tests/integration/conftest.py (function).
# The ai_messages table truncation is handled via CASCADE from users.
