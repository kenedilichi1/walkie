"""Walk-plan limits and defaults — the single source of truth.

The prompts quote these numbers to the LLM as rules, the reply validators
enforce the same numbers on the answer, and the wizard spin-box ranges on
them, so a policy change is one edit here instead of four.
"""

from __future__ import annotations

from typing import Any

MIN_HOUR = 6
MAX_HOUR = 21
MIN_DURATION = 5
MAX_DURATION = 180
MAX_SHIFT_MINUTES = 60  # how far the model may move the preferred start

DEFAULT_HHMM: tuple[int, int] = (12, 30)
DEFAULT_TIME = f"{DEFAULT_HHMM[0]:02d}:{DEFAULT_HHMM[1]:02d}"
DEFAULT_DURATION = 30


def coerce_duration(value: Any, default: int = DEFAULT_DURATION) -> int:
    """`value` as a duration inside [MIN_DURATION, MAX_DURATION], else `default`."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return default
    return minutes if MIN_DURATION <= minutes <= MAX_DURATION else default
