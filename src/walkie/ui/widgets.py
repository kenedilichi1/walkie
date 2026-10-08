"""Shared Qt widgets for time and duration entry."""

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import QSpinBox, QTimeEdit

from walkie import clock
from walkie.policy import DEFAULT_HHMM, USER_MAX_DURATION, USER_MIN_DURATION


def make_time_edit(value: str) -> QTimeEdit:
    """QTimeEdit showing 12h clock, holding an "HH:MM" string value."""
    edit = QTimeEdit()
    edit.setDisplayFormat("h:mm AP")
    edit.setTime(QTime(*(clock.parse_hhmm(value) or DEFAULT_HHMM)))
    return edit


def make_duration_spin(
    value: int, low: int = USER_MIN_DURATION, high: int = USER_MAX_DURATION
) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setSingleStep(5)
    spin.setSuffix(" min")
    spin.setValue(value)
    return spin
