"""Process-wide QApplication bootstrap (shared by wizard and quick-adjust)."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

_APP: QApplication | None = None


def ensure_app() -> QApplication:
    """Create the QApplication once and keep it alive for the process.

    The stored reference is the point: a QApplication whose last Python
    reference is dropped gets destroyed, and the next QWidget construction
    then aborts the process.
    """
    global _APP
    if _APP is None:
        existing = QApplication.instance()
        _APP = (
            existing if isinstance(existing, QApplication) else QApplication(sys.argv)
        )
    return _APP
