"""Password hashing and verification using bcrypt — Phase 1.

Phase 0 seed already stores bcrypt hashes. This module provides:
  - verify_password(plain, hashed) -> bool
  - hash_password(plain) -> str  (needed by conftest seed_hr fixture)
"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """Return bcrypt hash of *plain* password."""
    hashed: bytes = bcrypt.hashpw(plain.encode(), bcrypt.gensalt())
    return hashed.decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored bcrypt *hashed* value."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False
