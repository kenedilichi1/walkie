"""Offscreen smoke test for the quick-adjust dialog (walkie suggest --edit)."""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from walkie.models import Proposal
from walkie.storage import read_json
from walkie.ui.adjust_dialog import open_adjust_dialog
from walkie.ui.app import ensure_app


def _settle_dialog(accept: bool) -> None:
    """Accept/reject the open dialog once the event loop is running."""

    def settle() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog):
                widget.accept() if accept else widget.reject()

    QTimer.singleShot(0, settle)


def test_open_adjust_dialog_saves_on_accept(tmp_path):
    ensure_app()
    today_path = tmp_path / "today_plan.json"
    proposal = Proposal(suggested_time="16:30", duration_minutes=30, reason="rain")

    _settle_dialog(accept=True)
    saved = open_adjust_dialog(proposal, None, today_path=today_path)

    assert saved is True
    record = read_json(today_path)
    assert record["approved_by"] == "edit"
    assert record["suggested_time"] == "16:30"
    assert record["duration_minutes"] == 30


def test_open_adjust_dialog_cancel_writes_nothing(tmp_path):
    ensure_app()
    today_path = tmp_path / "today_plan.json"
    proposal = Proposal(suggested_time="16:30", duration_minutes=30)

    _settle_dialog(accept=False)
    saved = open_adjust_dialog(proposal, None, today_path=today_path)

    assert saved is False
    assert not today_path.exists()
