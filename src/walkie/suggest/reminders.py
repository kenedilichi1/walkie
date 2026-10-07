"""T-30/T-15/T-5 reminders, auto-approve at walk time, and the daemon."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path

from walkie import clock, config
from walkie.log import get_logger
from walkie.models import Proposal, TodayPlan, UserPlan, Weather
from walkie.storage import read_json, read_record, write_json
from walkie.suggest.proposals import ensure_proposal
from walkie.sync.notify import send_notification, with_quote
from walkie.weather import refresh_from_settings

log = get_logger("suggest")

REMINDER_OFFSETS_MIN = (30, 15, 5)

NotifyFn = Callable[[str, str], None]


def reminder_message(proposal: Proposal) -> str:
    return (
        f"{proposal.duration_minutes} min at {proposal.suggested_time} "
        f"({proposal.location_type.value}). Open walkie to adjust."
    )


def _today_walk(
    now: datetime, proposal_path: Path, today_path: Path
) -> tuple[Proposal, datetime] | None:
    """Today's pending walk (proposal, target time); None when nothing to do."""
    if today_path.exists():
        return None  # already approved or edited
    proposal = read_record(proposal_path, Proposal.from_dict)
    if proposal is None or proposal.for_date != clock.today_iso(now):
        return None  # never act on a missing or stale (yesterday's) proposal
    parsed = clock.parse_hhmm(proposal.suggested_time)
    if parsed is None:
        return None
    target = datetime.combine(now.date(), dtime(parsed[0], parsed[1]))
    return proposal, target


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
    due = _today_walk(now, proposal_path, today_path)
    if due is None:
        return []
    proposal, target = due
    state = read_json(state_path) or {}
    fired = state.get("fired", []) if state.get("date") == clock.today_iso(now) else []
    actions: list[str] = []

    for offset in REMINDER_OFFSETS_MIN:
        if offset in fired or now < target - timedelta(minutes=offset):
            continue
        notify_fn(
            f"walkie: walk at {proposal.suggested_time}",
            with_quote(reminder_message(proposal)),
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

    write_json(state_path, {"date": clock.today_iso(now), "fired": fired})
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
