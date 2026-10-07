"""T-30/T-15/T-5 reminders, auto-approve at walk time, and the daemon."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from walkie import clock, config
from walkie.clock import TIME_RE
from walkie.log import get_logger
from walkie.models import Proposal, TodayPlan, UserPlan, Weather
from walkie.storage import read_json, write_json
from walkie.suggest.proposals import ensure_proposal
from walkie.weather import refresh_from_settings

log = get_logger("suggest")

REMINDER_OFFSETS_MIN = (30, 15, 5)

NotifyFn = Callable[[str, str], None]


def send_notification(title: str, message: str) -> None:
    """Best-effort OS notification (logs when no desktop backend)."""
    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name="walkie", timeout=10)
    except Exception as exc:  # noqa: BLE001 - headless/log fallback
        log.info(f"notification unavailable ({exc}): {title} — {message}")


def reminder_message(proposal: Proposal) -> str:
    return (
        f"{proposal.duration_minutes} min at {proposal.suggested_time} "
        f"({proposal.location_type.value}). Open walkie to adjust."
    )


def check_reminders(
    now: datetime | None = None,
    notify_fn: NotifyFn | None = None,
    proposal_path: Path = config.PROPOSAL_PATH,
    today_path: Path = config.TODAY_PLAN_PATH,
    state_path: Path = config.REMINDER_STATE_PATH,
) -> list[str]:
    """Fire due reminders (T-30/T-15/T-5); auto-approve at walk time."""
    now = now or clock.now()
    notify_fn = notify_fn or send_notification
    data = read_json(proposal_path)
    if data is None or today_path.exists():
        return []
    proposal = Proposal.from_dict(data)
    if proposal.for_date != now.date().isoformat():
        return []  # never act on a stale (yesterday's) proposal
    if not TIME_RE.match(proposal.suggested_time):
        return []

    target = datetime.combine(
        now.date(),
        datetime.strptime(proposal.suggested_time, "%H:%M").time(),
    )
    state = read_json(state_path) or {}
    fired = state.get("fired", []) if state.get("date") == now.strftime("%Y-%m-%d") else []
    actions: list[str] = []

    for offset in REMINDER_OFFSETS_MIN:
        if offset in fired or now < target - timedelta(minutes=offset):
            continue
        notify_fn(
            f"walkie: walk at {proposal.suggested_time}",
            reminder_message(proposal),
        )
        fired.append(offset)
        actions.append(f"reminder-{offset}")

    if now >= target:
        record = proposal.approve(
            now.isoformat(timespec="seconds"), approved_by="auto"
        )
        write_json(today_path, record.to_dict())
        notify_fn(
            "walkie: walk approved",
            f"Auto-approved: {proposal.suggested_time}, "
            f"{proposal.duration_minutes} min. Have a good walk!",
        )
        actions.append("auto-approved")

    write_json(state_path, {"date": now.strftime("%Y-%m-%d"), "fired": fired})
    return actions


def write_today_plan(
    proposal: Proposal,
    when: str,
    duration: int,
    approved_by: str,
    now: datetime | None = None,
    today_path: Path = config.TODAY_PLAN_PATH,
) -> TodayPlan:
    now = now or clock.now()
    edited = replace(proposal, suggested_time=when, duration_minutes=duration)
    record = edited.approve(now.isoformat(timespec="seconds"), approved_by)
    write_json(today_path, record.to_dict())
    return record


def load_weather() -> Weather | None:
    settings = config.load_settings()
    return refresh_from_settings(settings)


def run_daemon(check_interval: float = 30.0) -> None:
    """Loop reminder checks until today's walk is approved or edited."""
    settings = config.load_settings()
    base_plan = config.load_user_plan()
    weather = refresh_from_settings(settings)
    ensure_proposal(base_plan, weather)
    try:
        while True:
            actions = check_reminders()
            if "auto-approved" in actions or config.TODAY_PLAN_PATH.exists():
                log.info("Walk approved for today; daemon exiting.")
                return
            time.sleep(check_interval)
    except KeyboardInterrupt:
        log.info("Daemon stopped.")


def load_base_plan() -> UserPlan:
    return config.load_user_plan()
