"""Qwen translation prompts — Phase 3 §3.4.

Step A: hi→ru translate + intent extract.
Step B: ru→hi translate (preserving citation markers).
"""

from __future__ import annotations

STEP_A_SYSTEM = (
    "You translate user questions from Hindi to Russian for a workplace assistant. "
    'Output JSON only: {"ru_query": "...", "intent": "schedule|location|payment|rules|other"}.'
)

STEP_B_SYSTEM = (
    "You translate Russian answers from a workplace assistant to Hindi. "
    "Preserve [1], [2], [3] citation markers exactly as-is. "
    "Output ONLY the Hindi translation."
)
