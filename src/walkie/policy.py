"""Walk-plan limits and defaults — the single source of truth.

Two scopes live here:

- What *you* may set (wizard, edit dialog, user_plan.json): any clock
  time, and a duration of USER_MIN_DURATION..USER_MAX_DURATION minutes
  — the range only catches typos, it is not a preference limit.
- What the *model* may answer (prompts, reply validators): nudge your
  start by at most MAX_SHIFT_MINUTES and your duration by at most
  DURATION_SHIFT_RATIO in either direction, never outside
  MIN_HOUR:00-MAX_HOUR:00 / MIN_DURATION..MAX_DURATION. Your choice is
  the anchor: when it sits outside the standing bounds, the model may
  only echo it back unchanged.

The prompts quote these numbers (see window_rules), the reply
validators enforce them (see reply_within_window), and the wizard
spin-box uses the user numbers, so a policy change is one edit here.
"""

from __future__ import annotations

from typing import Any

from walkie import clock

MIN_HOUR = 6
MAX_HOUR = 21
MIN_DURATION = 5
MAX_DURATION = 180
USER_MIN_DURATION = 5
USER_MAX_DURATION = 480
MAX_SHIFT_MINUTES = 60  # how far the model may move the preferred start
DURATION_SHIFT_RATIO = 0.5  # how far the model may scale the preferred duration

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


def fmt_hhmm(minutes: int) -> str:
    """Minutes-of-day -> zero-padded HH:MM."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_window_for(preferred_time: str) -> tuple[int, int] | None:
    """Inclusive minutes-of-day the model may propose; None = keep exactly.

    The window is the user's choice shifted by at most MAX_SHIFT_MINUTES,
    clipped to the standing MIN_HOUR:00-MAX_HOUR:00 bounds. A preferred
    time outside those bounds (or an unparseable one) is untouchable:
    the model may only echo it back.
    """
    parsed = clock.parse_hhmm(preferred_time)
    if parsed is None:
        return None
    preferred = parsed[0] * 60 + parsed[1]
    if not (MIN_HOUR * 60 <= preferred <= MAX_HOUR * 60):
        return None
    lo = max(MIN_HOUR * 60, preferred - MAX_SHIFT_MINUTES)
    hi = min(MAX_HOUR * 60, preferred + MAX_SHIFT_MINUTES)
    return lo, hi


def duration_window_for(preferred_duration: int) -> tuple[int, int] | None:
    """Inclusive minutes the model may propose; None = keep exactly.

    The window is the user's choice scaled by DURATION_SHIFT_RATIO in
    either direction, clipped to the standing duration bounds. A
    preferred duration outside those bounds is untouchable.
    """
    if not (
        isinstance(preferred_duration, int)
        and MIN_DURATION <= preferred_duration <= MAX_DURATION
    ):
        return None
    lo = max(MIN_DURATION, int(preferred_duration * (1 - DURATION_SHIFT_RATIO)))
    hi = min(MAX_DURATION, int(preferred_duration * (1 + DURATION_SHIFT_RATIO)))
    return lo, hi


def reply_within_window(
    proposed_time: object,
    proposed_duration: object,
    preferred_time: str,
    preferred_duration: int,
) -> bool:
    """Shape/range/shift check for one model reply — the trust boundary.

    The reply must stay inside the window around the user's own choice:
    the model may nudge, not redefine, and may always keep the user's
    exact values. Unparseable or out-of-window answers are rejected so
    the caller falls back to the user's plan.
    """
    parsed = clock.parse_hhmm(proposed_time)
    preferred = clock.parse_hhmm(preferred_time)
    if parsed is None or preferred is None:
        return False
    proposed = parsed[0] * 60 + parsed[1]
    wanted = preferred[0] * 60 + preferred[1]
    time_window = time_window_for(preferred_time)
    if proposed != wanted and (
        time_window is None
        or not (time_window[0] <= proposed <= time_window[1])
    ):
        return False
    if not isinstance(proposed_duration, int):
        return False
    duration_window = duration_window_for(preferred_duration)
    return proposed_duration == preferred_duration or (
        duration_window is not None
        and duration_window[0] <= proposed_duration <= duration_window[1]
    )

def window_rules(preferred_time: str, preferred_duration: int) -> str:
    """One prompt sentence: exactly what the model may change, and how."""
    time_window = time_window_for(preferred_time)
    if time_window is None:
        time_rule = (
            f"keep the start at exactly {preferred_time} "
            "(outside your allowed hours; do not propose another time)"
        )
    else:
        time_rule = (
            f"suggested_time between {fmt_hhmm(time_window[0])} and "
            f"{fmt_hhmm(time_window[1])} (their {preferred_time}, shifted "
            f"at most {MAX_SHIFT_MINUTES} min, inside "
            f"{MIN_HOUR:02d}:00-{MAX_HOUR:02d}:00)"
        )
    duration_window = duration_window_for(preferred_duration)
    if duration_window is None:
        duration_rule = (
            f"keep duration_minutes at exactly {preferred_duration} "
            "(outside your allowed range; do not propose another duration)"
        )
    else:
        duration_rule = (
            f"duration_minutes between {duration_window[0]} and "
            f"{duration_window[1]} (their {preferred_duration} min, "
            f"shifted at most {int(DURATION_SHIFT_RATIO * 100)}%)"
        )
    return f"{time_rule}; {duration_rule}"
