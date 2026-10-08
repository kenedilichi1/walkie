"""Walk-plan limits and defaults — the single source of truth.

Two scopes live here:

- What *you* may set (wizard, edit dialog, user_plan.json): any clock
  time, and a duration of USER_MIN_DURATION..USER_MAX_DURATION minutes
  — the range only catches typos, it is not a preference limit.
- What the *model* may answer (prompts, reply validators): a start
  within MIN_HOUR:00-MAX_HOUR:00 and MIN_DURATION..MAX_DURATION
  minutes.

The prompts quote the model numbers, the reply validators enforce them,
and the wizard spin-box uses the user numbers, so a policy change is one
edit here instead of four.
"""

from __future__ import annotations

from typing import Any

MIN_HOUR = 6
MAX_HOUR = 21
MIN_DURATION = 5
MAX_DURATION = 180
USER_MIN_DURATION = 5
USER_MAX_DURATION = 480
MAX_SHIFT_MINUTES = 60  # how far the model may move the preferred start

DEFAULT_HHMM: tuple[int, int] = (12, 30)
DEFAULT_TIME = f"{DEFAULT_HHMM[0]:02d}:{DEFAULT_HHMM[1]:02d}"
DEFAULT_DURATION = 30


def coerce_duration(value: Any, default: int = DEFAULT_DURATION) -> int:
    """`value` as a *model* duration inside [MIN_DURATION, MAX_DURATION]."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return default
    return minutes if MIN_DURATION <= minutes <= MAX_DURATION else default


def coerce_user_duration(value: Any, default: int = DEFAULT_DURATION) -> int:
    """`value` as a *user-chosen* duration inside the user range."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return default
    return minutes if USER_MIN_DURATION <= minutes <= USER_MAX_DURATION else default
