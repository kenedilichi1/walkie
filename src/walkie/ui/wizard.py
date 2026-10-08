"""One-time interactive setup wizard (PyQt6).

Confirms where walks start (IP guess, pasted map link, or typed address),
asks for preferred walk time, duration, intensity and shade/sun
preference, confirms the plan with the local LLM, then saves the start
point into config/settings.yaml and the plan into config/user_plan.json.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from walkie import clock, config, geo, region
from walkie.llm import complete
from walkie.log import get_logger
from walkie.models import Intensity, LocationType, UserPlan
from walkie.suggest.prompts import build_confirmation_prompt, describe_plan
from walkie.ui.app import ensure_app
from walkie.ui.widgets import make_duration_spin, make_time_edit

log = get_logger("wizard")

DetectedLocation = tuple[float, float, str, str, str]

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


def _choice_index(choices: Sequence[tuple[object, str]], value: object) -> int:
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


def detect_guess() -> DetectedLocation | None:
    """IP-detected location for the start-point guess; None when offline."""
    try:
        return region.detect_location()
    except region.RegionError as exc:
        log.info(f"start-point guess unavailable: {exc}")
        return None


def saved_point() -> tuple[float, float] | None:
    """The configured start point, when settings.yaml holds one."""
    try:
        current = config.load_settings()
    except config.ConfigError as exc:
        log.info(f"no saved start point: {exc}")
        return None
    return (current.lat, current.lon)


def save_start_point(
    point: tuple[float, float],
    detected: DetectedLocation | None = None,
    settings_path: Path = config.SETTINGS_PATH,
) -> None:
    """Persist the chosen start point.

    Timezone is written only when the point is the one IP detection found —
    a pasted link must not drag the timezone along with it.
    """
    tz = detected[4] if detected and point == (detected[0], detected[1]) else None
    region.set_location(point[0], point[1], tz=tz, settings_path=settings_path)


class StartPointPage(QWizardPage):
    """First screen: accept the guessed start point, or override it."""

    def __init__(self, guess: tuple[float, float] | None = None) -> None:
        super().__init__()
        self.setTitle("Where do your walks start?")
        self.setSubTitle("walkie plans every loop from this point.")
        self._guess = guess
        self._chosen: tuple[float, float] | None = None

        layout = QVBoxLayout(self)
        if guess:
            self.guess_label = QLabel(
                f"We think you start near {guess[0]:.5f}, {guess[1]:.5f}."
            )
        else:
            self.guess_label = QLabel(
                "We couldn't guess your start point — "
                "paste a map link or type an address."
            )
        self.guess_label.setWordWrap(True)
        layout.addWidget(self.guess_label)

        self.use_guess_btn = QRadioButton("Yes, start walks from here")
        self.use_guess_btn.setEnabled(guess is not None)
        self.use_guess_btn.setChecked(guess is not None)
        self.paste_btn = QRadioButton("Paste a map link or coordinates")
        self.address_btn = QRadioButton("Type an address or landmark")
        if guess is None:
            self.paste_btn.setChecked(True)
        for button in (self.use_guess_btn, self.paste_btn, self.address_btn):
            layout.addWidget(button)

        self.paste_edit = QLineEdit()
        self.paste_edit.setPlaceholderText(
            "https://maps.app.goo.gl/… or 6.31625, 8.11691"
        )
        self.paste_edit.setAccessibleName("map link or coordinates")
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("e.g. Obudu Cattle Ranch")
        self.address_edit.setAccessibleName("address or landmark")
        layout.addWidget(self.paste_edit)
        layout.addWidget(self.address_edit)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        self.paste_btn.toggled.connect(self.paste_edit.setVisible)
        self.address_btn.toggled.connect(self.address_edit.setVisible)
        self.paste_edit.textChanged.connect(self._paste_status)
        self.paste_edit.setVisible(False)
        self.address_edit.setVisible(False)

    def _paste_status(self, text: str) -> None:
        point = geo.parse_place(text)
        self.status_label.setText(
            f"Start point: {point[0]:.5f}, {point[1]:.5f}" if point else ""
        )

    def validatePage(self) -> bool:
        """Resolve the chosen mode to coordinates, or stay on the page."""
        if self.use_guess_btn.isChecked():
            if self._guess is None:
                self.status_label.setText(
                    "No guess available — paste a link or type an address."
                )
                return False
            self._chosen = self._guess
            return True
        if self.paste_btn.isChecked():
            text = self.paste_edit.text().strip()
            point = geo.parse_place(text)
            if point is None and text:
                point = region.resolve_link(text)
            if point is None:
                self.status_label.setText(
                    "No coordinates found — long-press a spot in your maps "
                    "app and copy the coordinates instead."
                )
                return False
            self._chosen = point
            return True
        hit = region.geocode_place(self.address_edit.text())
        if hit is None:
            self.status_label.setText(
                "Couldn't find that place — check the spelling, or paste "
                "a map link instead."
            )
            return False
        lat, lon, name = hit
        self._chosen = (lat, lon)
        self.status_label.setText(f"Start point: {name}")
        return True

    def start_point(self) -> tuple[float, float] | None:
        """Resolved coordinates once Next has been pressed."""
        return self._chosen


class PlanWizard(QWizard):
    """Three-page wizard: start point, when, then intensity/location type."""

    def __init__(
        self,
        plan: UserPlan | None = None,
        guess: tuple[float, float] | None = None,
    ) -> None:
        super().__init__()
        current = plan or load_saved_plan()
        self.setWindowTitle("walkie — setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self.start_page = StartPointPage(guess)

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

        self.addPage(self.start_page)
        self.addPage(when_page)
        self.addPage(where_page)

    def start_point(self) -> tuple[float, float] | None:
        """Coordinates the start-point page settled on, once Next was pressed."""
        return self.start_page.start_point()

    def plan(self) -> UserPlan:
        return UserPlan(
            preferred_time=self.time_edit.time().toString("HH:mm"),
            duration_minutes=self.duration_spin.value(),
            location_type=LOCATION_CHOICES[self.location_combo.currentIndex()][0],
            intensity=INTENSITY_CHOICES[self.intensity_combo.currentIndex()][0],
            area=self.area_edit.text().strip(),
        )


def confirm_with_user(
    plan: UserPlan,
    guess: tuple[float, float] | None = None,
) -> UserPlan | None:
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
        wizard = PlanWizard(plan, guess=guess)
        if not wizard.exec():
            return None
        plan = wizard.plan()


def run_setup() -> None:
    app = ensure_app()
    app.setApplicationName("walkie-setup")

    detected = detect_guess()
    guess = (detected[0], detected[1]) if detected else saved_point()

    wizard = PlanWizard(guess=guess)
    if not wizard.exec():
        log.info("Setup cancelled.")
        return

    plan = confirm_with_user(wizard.plan(), guess)
    if plan is None:
        log.info("Setup cancelled.")
        return

    record = save_plan(plan)
    point = wizard.start_point() or guess
    if point is None:
        log.warning("No start point chosen; settings location untouched.")
    else:
        save_start_point(point, detected)
        log.info(f"Start point set to {point[0]:.5f}, {point[1]:.5f}")
    QMessageBox.information(
        None,
        "You're set!",
        f"Plan saved to {config.USER_PLAN_PATH.name}.\n\n“{record.quote}”",
    )
    log.info(f"Saved plan to {config.USER_PLAN_PATH}")
