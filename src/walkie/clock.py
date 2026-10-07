"""Local wall-clock time.

All timestamps stored in JSON are local naive ISO strings (no offset), so
schedule comparisons (proposal deadlines, reminder targets) stay consistent.
"""

import re
from datetime import datetime

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def now() -> datetime:
    return datetime.now()


def iso_now() -> str:
    return now().isoformat(timespec="seconds")
