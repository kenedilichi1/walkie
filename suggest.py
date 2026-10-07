#!/usr/bin/env python3
"""Daily walk proposal: one local-LLM call, quick edit, reminders, auto-approve.

Modes:
  python suggest.py                    build or refresh today's proposal
  python suggest.py --edit             quick GUI edit -> output/today_plan.json
  python suggest.py --check-reminders  fire due reminders (cron every few min)
  python suggest.py --daemon           loop reminder checks until approved
  python suggest.py --force-new        regenerate even if the proposal is valid

Reminders fire at 30, 15 and 5 minutes before the suggested walk time;
if nobody edits by walk time, the proposal auto-approves to today_plan.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import ollama
import requests
import yaml

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "config" / "settings.yaml"
USER_PLAN_PATH = ROOT / "config" / "user_plan.json"
PROPOSAL_PATH = ROOT / "output" / "proposal.json"
TODAY_PLAN_PATH = ROOT / "output" / "today_plan.json"
REMINDER_STATE_PATH = ROOT / "output" / "reminder_state.json"

REMINDER_OFFSETS_MIN = (30, 15, 5)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def log(message: str) -> None:
    print(message, file=sys.stderr)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def load_settings() -> dict:
    try:
        return yaml.safe_load(SETTINGS_PATH.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def weather_fingerprint(weather: dict | None) -> str:
    """Bucketed fingerprint: stable across jitter, flips when conditions change."""
    if not weather:
        return "unavailable"
    temp = weather.get("temperature_2m") or 0.0
    rain = weather.get("precipitation_probability_max") or 0
    rain_bucket = next(
        (
            label
            for limit, label in ((10, "low"), (30, "mild"), (60, "med"))
            if rain <= limit
        ),
        "high",
    )
    return f"{weather.get('summary')}|{round(temp / 5) * 5:.0f}C|{rain_bucket}"


def weather_line(weather: dict | None) -> str:
    if not weather:
        return "weather unavailable (offline)"
    temp = weather.get("temperature_2m")
    high = weather.get("temperature_2m_max", temp)
    return (
        f"{weather.get('summary', 'unknown')}, {temp}C "
        f"(high {high}C), "
        f"rain chance {weather.get('precipitation_probability_max', 0)}%, "
        f"wind {weather.get('wind_speed_10m', '?')} km/h"
    )


def build_prompt(base_plan: dict, weather: dict | None) -> str:
    area = f", near {base_plan['area']}" if base_plan.get("area") else ""
    return (
        "Plan one walk today. Base plan: "
        f"{base_plan['duration_minutes']} min at {base_plan['preferred_time']}, "
        f"{base_plan['location_type']} preferred, "
        f"{base_plan['intensity']} intensity{area}. "
        f"Today's weather: {weather_line(weather)}. "
        "Rules: rain chance over 30% -> keep shade; shift start by at most "
        "60 min to dodge bad weather; time must stay within 06:00-21:00; "
        "duration 5-120 min. "
        'Reply with ONLY a JSON object: {"suggested_time":"HH:MM",'
        '"duration_minutes":N,"reason":"one sentence why",'
        '"route_notes":"one short routing tip"}. No other text.'
    )


def parse_llm_json(text: str) -> dict | None:
    """Extract and validate the JSON object from an LLM reply."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    when = data.get("suggested_time")
    duration = data.get("duration_minutes")
    if not isinstance(when, str) or not TIME_RE.match(when):
        return None
    if not isinstance(duration, int) or not 5 <= duration <= 180:
        return None
    hour, minute = int(when.split(":")[0]), int(when.split(":")[1])
    if hour > 21 or (hour == 21 and minute > 0) or hour < 6:
        return None
    return data


def call_llm(prompt: str) -> dict | None:
    host, model = _model_config()
    try:
        response = ollama.Client(host=host).chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3, "num_predict": 300},
        )
        text = _response_text(response)
        if not text:
            return None
        return parse_llm_json(text)
    except Exception as exc:  # noqa: BLE001 - local LLM is best-effort
        log(f"  ollama unavailable ({exc})")
        return None


def _response_text(response: object) -> str | None:
    message = getattr(response, "message", None)
    text = getattr(message, "content", None)
    if not text and isinstance(response, dict):
        text = response.get("message", {}).get("content")
    return text.strip() if text else None


def _model_config() -> tuple[str, str]:
    ollama_cfg = load_settings().get("ollama", {})
    return (
        str(ollama_cfg.get("host", "http://localhost:11434")),
        str(ollama_cfg.get("model", "llama3.2:3b")),
    )


def make_proposal(
    base_plan: dict, weather: dict | None, llm: dict | None
) -> dict:
    """Assemble the proposal; falls back to base prefs when the LLM fails."""
    when = (llm or {}).get("suggested_time") or base_plan["preferred_time"]
    duration = (llm or {}).get("duration_minutes") or base_plan["duration_minutes"]
    hour, minute = int(when.split(":")[0]), int(when.split(":")[1])
    reason = (llm or {}).get("reason")
    if not reason:
        reason = "Kept your base plan (model reply wasn't usable)."
    approve_by = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {
        "suggested_time": f"{hour:02d}:{minute:02d}",
        "duration_minutes": int(duration),
        "location_type": base_plan.get("location_type", "shade"),
        "intensity": base_plan.get("intensity", "moderate"),
        "area": base_plan.get("area", ""),
        "weather_summary": weather_line(weather),
        "weather_fingerprint": weather_fingerprint(weather),
        "reason": reason,
        "route_notes": (llm or {}).get("route_notes", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "approve_by": approve_by.isoformat(timespec="minutes"),
    }


def proposal_is_valid(proposal: dict, weather: dict | None, now: datetime) -> bool:
    deadline = proposal.get("approve_by")
    if not deadline:
        return False
    try:
        if datetime.fromisoformat(deadline) <= now:
            return False
    except ValueError:
        return False
    return proposal.get("weather_fingerprint") == weather_fingerprint(weather)


def ensure_proposal(
    base_plan: dict,
    weather: dict | None,
    now: datetime | None = None,
    force: bool = False,
    proposal_path: Path = PROPOSAL_PATH,
) -> dict:
    """Reuse today's valid proposal, or generate a fresh one."""
    now = now or datetime.now()
    existing = read_json(proposal_path)
    if existing and not force and proposal_is_valid(existing, weather, now):
        log("Reusing today's proposal.")
        return existing
    proposal = make_proposal(base_plan, weather, call_llm(build_prompt(base_plan, weather)))
    write_json(proposal_path, proposal)
    log(f"Proposal written: walk at {proposal['suggested_time']} "
        f"({proposal['duration_minutes']} min) — {proposal['reason']}")
    return proposal


def send_notification(title: str, message: str) -> None:
    """Best-effort OS notification (logs when no desktop backend)."""
    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name="walkie", timeout=10)
    except Exception as exc:  # noqa: BLE001 - headless/log fallback
        log(f"  notification unavailable ({exc}): {title} — {message}")


def reminder_message(proposal: dict) -> str:
    return (
        f"{proposal['duration_minutes']} min at {proposal['suggested_time']} "
        f"({proposal['location_type']}). Adjust with: python suggest.py --edit"
    )


def check_reminders(
    now: datetime | None = None,
    notify_fn=None,
    proposal_path: Path = PROPOSAL_PATH,
    today_path: Path = TODAY_PLAN_PATH,
    state_path: Path = REMINDER_STATE_PATH,
) -> list[str]:
    """Fire due reminders (T-30/T-15/T-5); auto-approve at walk time."""
    now = now or datetime.now()
    notify_fn = notify_fn or send_notification
    proposal = read_json(proposal_path)
    if proposal is None or today_path.exists():
        return []
    if not TIME_RE.match(proposal.get("suggested_time", "")):
        return []

    target = datetime.combine(
        now.date(),
        datetime.strptime(proposal["suggested_time"], "%H:%M").time(),
    )
    state = read_json(state_path) or {}
    fired = state.get("fired", []) if state.get("date") == now.strftime("%Y-%m-%d") else []
    actions: list[str] = []

    for offset in REMINDER_OFFSETS_MIN:
        if offset in fired or now < target - timedelta(minutes=offset):
            continue
        notify_fn(f"walkie: walk at {proposal['suggested_time']}",
                  reminder_message(proposal))
        fired.append(offset)
        actions.append(f"reminder-{offset}")

    if now >= target:
        write_json(today_path, {
            **proposal,
            "approved_at": now.isoformat(timespec="seconds"),
            "approved_by": "auto",
        })
        notify_fn("walkie: walk approved",
                  f"Auto-approved: {proposal['suggested_time']}, "
                  f"{proposal['duration_minutes']} min. Have a good walk!")
        actions.append("auto-approved")

    write_json(state_path, {"date": now.strftime("%Y-%m-%d"), "fired": fired})
    return actions


def write_today_plan(
    proposal: dict,
    when: str,
    duration: int,
    approved_by: str,
    now: datetime | None = None,
    today_path: Path = TODAY_PLAN_PATH,
) -> dict:
    record = {
        **proposal,
        "suggested_time": when,
        "duration_minutes": duration,
        "approved_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "approved_by": approved_by,
    }
    write_json(today_path, record)
    return record


def open_adjust_dialog(
    proposal: dict,
    existing: dict | None,
    today_path: Path = TODAY_PLAN_PATH,
) -> bool:
    """Quick edit window (time/duration); returns False if cancelled."""
    from PyQt6.QtCore import QTime
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QLabel,
        QSpinBox,
        QTimeEdit,
    )

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = QDialog()
    dialog.setWindowTitle("Adjust today's walk")
    current = existing or proposal

    layout = QFormLayout(dialog)
    time_edit = QTimeEdit()
    time_edit.setDisplayFormat("h:mm AP")
    hour, minute = (int(part) for part in current["suggested_time"].split(":"))
    time_edit.setTime(QTime(hour, minute))
    duration_spin = QSpinBox()
    duration_spin.setRange(5, 180)
    duration_spin.setSingleStep(5)
    duration_spin.setSuffix(" min")
    duration_spin.setValue(int(current["duration_minutes"]))
    layout.addRow(QLabel("Start time:"), time_edit)
    layout.addRow(QLabel("Duration:"), duration_spin)
    layout.addRow(QLabel(f"Why: {current.get('reason', '')}"))

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
    )
    return True


def run_daemon(check_interval: float = 30.0) -> None:
    """Loop reminder checks until today's walk is approved or edited."""
    ensure_proposal(_load_base_plan(), _load_weather())
    while True:
        actions = check_reminders()
        if "auto-approved" in actions or TODAY_PLAN_PATH.exists():
            log("Walk approved for today; daemon exiting.")
            return
        time.sleep(check_interval)


def _load_base_plan() -> dict:
    plan = read_json(USER_PLAN_PATH)
    if plan is None:
        sys.exit(f"error: {USER_PLAN_PATH} missing — run: python setup_gui.py")
    return plan


def _load_weather() -> dict | None:
    from weather.fetcher import refresh_if_stale

    settings = load_settings()
    location = settings.get("location", {})
    weather_cfg = settings.get("weather", {})
    cache_path = ROOT / str(weather_cfg.get("cache", "cache/weather_today.json"))
    forecast_url = str(
        weather_cfg.get("forecast_url", "https://api.open-meteo.com/v1/forecast")
    )
    return refresh_if_stale(
        cache_path,
        float(location.get("lat", 0.0)),
        float(location.get("lon", 0.0)),
        str(location.get("timezone", "UTC")),
        url=forecast_url,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edit", action="store_true",
                        help="open the quick-adjust dialog")
    parser.add_argument("--check-reminders", action="store_true",
                        help="fire due reminders once, then exit")
    parser.add_argument("--daemon", action="store_true",
                        help="loop reminder checks until approved")
    parser.add_argument("--force-new", action="store_true",
                        help="regenerate the proposal even if still valid")
    args = parser.parse_args()

    if args.check_reminders:
        for action in check_reminders():
            log(action)
        return
    if args.daemon:
        run_daemon()
        return

    base_plan = _load_base_plan()
    weather = _load_weather()
    if args.edit:
        proposal = ensure_proposal(base_plan, weather)
        if open_adjust_dialog(proposal, read_json(TODAY_PLAN_PATH)):
            log("Edited plan saved to output/today_plan.json")
        return

    proposal = ensure_proposal(base_plan, weather, force=args.force_new)
    if TODAY_PLAN_PATH.exists():
        log("Today's walk is already approved — see output/today_plan.json")
    else:
        log(f"Edit before {proposal['suggested_time']}: "
            "python suggest.py --edit (or wait for auto-approve)")


if __name__ == "__main__":
    main()
