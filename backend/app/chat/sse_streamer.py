"""SSE event encoding helpers — Phase 3."""

from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event string.

    Format:
        event: <name>\\n
        data: <json>\\n
        \\n
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
