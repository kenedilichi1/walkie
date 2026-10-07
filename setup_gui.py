#!/usr/bin/env python3
"""One-time interactive setup wizard for walkie (PyQt6).

Asks for your preferred walk time, duration, intensity and shade/sun
preference, confirms the plan with the local LLM, then saves it to
config/user_plan.json and shows a motivational quote from config/quotes.txt.

Usage: python setup_gui.py
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import ollama
import yaml
from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "config" / "settings.yaml"
QUOTES_PATH = ROOT / "config" / "quotes.txt"
PLAN_PATH = ROOT / "config" / "user_plan.json"

DEFAULT_PLAN = {
    "preferred_time": "12:30",
    "duration_minutes": 30,
    "location_type": "shade",   # shade | sun | any
    "intensity": "moderate",    # relaxed | moderate | brisk
    "area": "",
}

LOCATION_LABELS = ["Shade preferred", "Sun preferred", "No preference"]
LOCATION_VALUES = ["shade", "sun", "any"]
INTENSITY_LABELS = ["Relaxed", "Moderate", "Brisk"]
INTENSITY_VALUES = ["relaxed", "moderate", "brisk"]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def load_quotes() -> list[str]:
    """Read editable quotes, skipping blanks and # comments."""
    if not QUOTES_PATH.exists():
        return ["Stand up from your computer."]
    quotes = [
        line.strip()
        for line in QUOTES_PATH.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return quotes or ["Stand up from your computer."]


def pick_quote() -> str:
    return random.choice(load_quotes())


def load_saved_plan() -> dict:
    if PLAN_PATH.exists():
        try:
            saved = json.loads(PLAN_PATH.read_text())
            return {**DEFAULT_PLAN, **saved}
        except (json.JSONDecodeError, OSError):
            log(f"  could not read {PLAN_PATH}; using defaults")
    return dict(DEFAULT_PLAN)


def save_plan(plan: dict) -> dict:
    """Persist plan + quote + timestamp to config/user_plan.json."""
    record = {
        **plan,
        "quote": plan.get("quote") or pick_quote(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    PLAN_PATH.write_text(json.dumps(record, indent=2) + "\n")
    return record


def describe_plan(plan: dict) -> str:
    """Plain-language plan summary used as LLM prompt and fallback reply."""
    parts = [f"{plan['duration_minutes']} min at {plan['preferred_time']}"]
    if plan.get("area"):
        parts.append(f"near {plan['area']}")
    parts.append(f"{plan['location_type']} preferred")
    parts.append(f"{plan['intensity']} intensity")
    return ", ".join(parts)


def fallback_confirmation(plan: dict) -> str:
    return f"{describe_plan(plan)} — sound good?"


def llm_confirmation(plan: dict) -> str:
    """One-sentence confirmation from the local model; fallback on failure."""
    host, model = _model_config()
    prompt = (
        "Confirm a walking plan with the user. Reply with exactly ONE "
        "sentence (max 25 words): summarize the plan and ask 'sound good?' "
        "in a friendly casual tone. No lists, no extra text. "
        f"Plan: {describe_plan(plan)}."
    )
    try:
        client = ollama.Client(host=host)
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3, "num_predict": 60},
        )
        text = _response_text(response)
        if text:
            return text.splitlines()[0][:300]
        log("  ollama returned empty text; using template confirmation")
    except Exception as exc:  # noqa: BLE001 - local LLM is best-effort
        log(f"  ollama unavailable ({exc}); using template confirmation")
    return fallback_confirmation(plan)


def _response_text(response: object) -> str | None:
    message = getattr(response, "message", None)
    text = getattr(message, "content", None)
    if not text and isinstance(response, dict):
        text = response.get("message", {}).get("content")
    return text.strip() if text else None


def _model_config() -> tuple[str, str]:
    try:
        settings = yaml.safe_load(SETTINGS_PATH.read_text()) or {}
        ollama_cfg = settings.get("ollama", {})
        return (
            str(ollama_cfg.get("host", "http://localhost:11434")),
            str(ollama_cfg.get("model", "llama3.2:3b")),
        )
    except (OSError, yaml.YAMLError):
        return "http://localhost:11434", "llama3.2:3b"


class PlanWizard(QWizard):
    """Two-page wizard: when/where, then intensity/location type."""

    def __init__(self, plan: dict | None = None):
        super().__init__()
        current = plan or load_saved_plan()
        self.setWindowTitle("walkie — setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("h:mm AP")
        hour, minute = (int(part) for part in current["preferred_time"].split(":"))
        self.time_edit.setTime(QTime(hour, minute))
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 180)
        self.duration_spin.setSingleStep(5)
        self.duration_spin.setSuffix(" min")
        self.duration_spin.setValue(int(current["duration_minutes"]))
        when_page = QWizardPage()
        when_page.setTitle("When do you want to walk?")
        when_layout = QFormLayout(when_page)
        when_layout.addRow(QLabel("Preferred start time:"), self.time_edit)
        when_layout.addRow(QLabel("How long:"), self.duration_spin)

        self.location_combo = QComboBox()
        self.location_combo.addItems(LOCATION_LABELS)
        self.location_combo.setCurrentIndex(
            LOCATION_VALUES.index(current["location_type"])
        )
        self.intensity_combo = QComboBox()
        self.intensity_combo.addItems(INTENSITY_LABELS)
        self.intensity_combo.setCurrentIndex(
            INTENSITY_VALUES.index(current["intensity"])
        )
        self.area_edit = QLineEdit(current.get("area", ""))
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

    def plan(self) -> dict:
        return {
            "preferred_time": self.time_edit.time().toString("HH:mm"),
            "duration_minutes": self.duration_spin.value(),
            "location_type": LOCATION_VALUES[self.location_combo.currentIndex()],
            "intensity": INTENSITY_VALUES[self.intensity_combo.currentIndex()],
            "area": self.area_edit.text().strip(),
        }


def confirm_with_user(plan: dict) -> dict | None:
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


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("walkie-setup")

    wizard = PlanWizard()
    if not wizard.exec():
        log("Setup cancelled.")
        return

    plan = confirm_with_user(wizard.plan())
    if plan is None:
        log("Setup cancelled.")
        return

    record = save_plan(plan)
    QMessageBox.information(
        None,
        "You're set!",
        f"Plan saved to {PLAN_PATH.name}.\n\n“{record['quote']}”",
    )
    log(f"Saved plan to {PLAN_PATH}")


if __name__ == "__main__":
    main()
