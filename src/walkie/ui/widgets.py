"""Shared Qt widgets for time and duration entry."""

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import QSpinBox, QTimeEdit


def make_time_edit(value: str) -> QTimeEdit:
    """QTimeEdit showing 12h clock, holding an "HH:MM" string value."""
    edit = QTimeEdit()
    edit.setDisplayFormat("h:mm AP")
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError:
        hour, minute = 12, 30  # tolerate hand-edited config
    edit.setTime(QTime(hour, minute))
    return edit


def make_duration_spin(value: int, low: int = 5, high: int = 180) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setSingleStep(5)
    spin.setSuffix(" min")
    spin.setValue(value)
    return spin
