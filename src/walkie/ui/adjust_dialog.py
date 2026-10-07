"""Quick-adjust dialog for today's walk (time + duration)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
)

from walkie import config
from walkie.models import Proposal, TodayPlan
from walkie.suggest.reminders import write_today_plan
from walkie.ui.app import ensure_app
from walkie.ui.widgets import make_duration_spin, make_time_edit


def open_adjust_dialog(
    proposal: Proposal,
    existing: TodayPlan | None,
    today_path: Path = config.TODAY_PLAN_PATH,
) -> bool:
    """Quick edit window (time/duration); returns False if cancelled."""
    ensure_app()
    dialog = QDialog()
    dialog.setWindowTitle("Adjust today's walk")
    current: Proposal = existing or proposal

    layout = QFormLayout(dialog)
    time_edit = make_time_edit(current.suggested_time)
    duration_spin = make_duration_spin(current.duration_minutes)
    layout.addRow(QLabel("Start time:"), time_edit)
    layout.addRow(QLabel("Duration:"), duration_spin)
    layout.addRow(QLabel(f"Why: {current.reason}"))

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save
        | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    write_today_plan(
        proposal,
        time_edit.time().toString("HH:mm"),
        duration_spin.value(),
        approved_by="edit",
        today_path=today_path,
    )
    return True
