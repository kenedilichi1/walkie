"""One-time interactive setup wizard (PyQt6).

Asks for preferred walk time, duration, intensity and shade/sun
preference, confirms the plan with the local LLM, then saves it to
config/user_plan.json and shows a motivational quote.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWizard,
    QWizardPage,
    QVBoxLayout,
)

from walkie import clock, config
from walkie.llm import complete
from walkie.log import get_logger
from walkie.models import Intensity, LocationType, UserPlan
from walkie.suggest.prompts import build_confirmation_prompt, describe_plan
from walkie.ui.widgets import make_duration_spin, make_time_edit

log = get_logger("wizard")

LOCATION_CHOICES: list[tuple[LocationType, str]] = [
    (LocationType.SHADE, "Shade preferred"),
    (LocationType.SUN, "Sun preferred"),
    (LocationType.ANY, "No preference"),
]
INTENSITY_CHOICES: list[tuple[Intensity, str]] = [
    (Intensity.RELAXED, "Relaxed"),
    (Intensity.MODERATE, "Moderate"),
    (Intensity.BRISK, "Brisk"),
]


def _choice_index(choices: list[tuple[object, str]], value: object) -> int:
    for index, (member, _label) in enumerate(choices):
        if member == value:
            return index
    return 0


def load_saved_plan(path: Path = config.USER_PLAN_PATH) -> UserPlan:
    try:
        return config.load_user_plan(path)
    except config.ConfigError:
        return UserPlan()


def save_plan(plan: UserPlan, path: Path = config.USER_PLAN_PATH) -> UserPlan:
    """Persist plan + quote + timestamp to config/user_plan.json."""
    record = replace(
        plan,
        quote=plan.quote or config.pick_quote(),
        created_at=clock.iso_now(),
    )
    config.save_user_plan(record, path)
    return record


def fallback_confirmation(plan: UserPlan) -> str:
    return f"{describe_plan(plan)} — sound good?"


def llm_confirmation(plan: UserPlan) -> str:
    """One-sentence confirmation from the local model; template on failure."""
    text = complete(build_confirmation_prompt(plan), max_tokens=60)
    if text:
        return text.splitlines()[0][:300]
    log.info("no usable model reply; using template confirmation")
    return fallback_confirmation(plan)


class PlanWizard(QWizard):
    """Two-page wizard: when/where, then intensity/location type."""

    def __init__(self, plan: UserPlan | None = None):
        super().__init__()
        current = plan or load_saved_plan()
        self.setWindowTitle("walkie — setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self.time_edit = make_time_edit(current.preferred_time)
        self.duration_spin = make_duration_spin(current.duration_minutes)
        when_page = QWizardPage()
        when_page.setTitle("When do you want to walk?")
        when_layout = QFormLayout(when_page)
        when_layout.addRow(QLabel("Preferred start time:"), self.time_edit)
        when_layout.addRow(QLabel("How long:"), self.duration_spin)

        self.location_combo = QComboBox()
        self.location_combo.addItems([label for _m, label in LOCATION_CHOICES])
        self.location_combo.setCurrentIndex(
            _choice_index(LOCATION_CHOICES, current.location_type)
        )
        self.intensity_combo = QComboBox()
        self.intensity_combo.addItems([label for _m, label in INTENSITY_CHOICES])
        self.intensity_combo.setCurrentIndex(
            _choice_index(INTENSITY_CHOICES, current.intensity)
        )
        self.area_edit = QLineEdit(current.area)
        self.area_edit.setPlaceholderText("optional, e.g. Riverside")
        where_page = QWizardPage()
        where_page.setTitle("Where and how intense?")
        where_layout = QVBoxLayout(where_page)
        form = QFormLayout()
        form.addRow(QLabel("Location type:"), self.location_combo)
        form.addRow(QLabel("Intensity:"), self.intensity_combo)
        form.addRow(QLabel("Area / landmark:"), self.area_edit)
        where_layout.addLayout(form)

        self.addPage(when_page)
        self.addPage(where_page)

    def plan(self) -> UserPlan:
        return UserPlan(
            preferred_time=self.time_edit.time().toString("HH:mm"),
            duration_minutes=self.duration_spin.value(),
            location_type=LOCATION_CHOICES[self.location_combo.currentIndex()][0],
            intensity=INTENSITY_CHOICES[self.intensity_combo.currentIndex()][0],
            area=self.area_edit.text().strip(),
        )


def confirm_with_user(plan: UserPlan) -> UserPlan | None:
    """LLM confirm loop; returns confirmed plan or None if the user quits."""
    while True:
        sentence = llm_confirmation(plan)
        answer = QMessageBox.question(
            None,
            "Confirm your walk",
            sentence,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            return plan
        wizard = PlanWizard(plan)
        if not wizard.exec():
            return None
        plan = wizard.plan()


def run_setup() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("walkie-setup")

    wizard = PlanWizard()
    if not wizard.exec():
        log.info("Setup cancelled.")
        return 0

    plan = confirm_with_user(wizard.plan())
    if plan is None:
        log.info("Setup cancelled.")
        return 0

    record = save_plan(plan)
    QMessageBox.information(
        None,
        "You're set!",
        f"Plan saved to {config.USER_PLAN_PATH.name}.\n\n“{record.quote}”",
    )
    log.info(f"Saved plan to {config.USER_PLAN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(run_setup())
