"""Local wall-clock time.

All timestamps stored in JSON are local naive ISO strings (no offset), so
schedule comparisons (proposal deadlines, reminder targets) stay consistent.
"""

from datetime import datetime


def now() -> datetime:
    return datetime.now()


def iso_now() -> str:
    return now().isoformat(timespec="seconds")
