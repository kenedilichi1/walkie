"""Local wall-clock time.

All timestamps stored in JSON are local naive ISO strings (no offset), so
schedule comparisons (proposal deadlines, reminder targets) stay consistent.
"""

from __future__ import annotations

import re
from datetime import datetime

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def now() -> datetime:
    return datetime.now()


def iso_now(at: datetime | None = None) -> str:
    return (at or now()).isoformat(timespec="seconds")


def today_iso(at: datetime | None = None) -> str:
    """YYYY-MM-DD of `at` — the one "is this record from today" idiom."""
    return (at or now()).date().isoformat()


def parse_hhmm(value: object) -> tuple[int, int] | None:
    """Strict "HH:MM" -> (hour, minute); None unless the time is 00:00-23:59.

    TIME_RE only shape-checks, so "12:75" matches it — every consumer that
    goes on to call int() or strptime() must gate on this instead.
    """
    if not isinstance(value, str) or not TIME_RE.match(value):
        return None
    hour_s, minute_s = value.split(":")
    hour, minute = int(hour_s), int(minute_s)
    return (hour, minute) if hour <= 23 and minute <= 59 else None


def parse_first(*candidates: object) -> tuple[int, int] | None:
    """First usable "HH:MM" among `candidates`, in order; None when none is."""
    for candidate in candidates:
        parsed = parse_hhmm(candidate)
        if parsed is not None:
            return parsed
    return None
