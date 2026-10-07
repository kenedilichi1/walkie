"""AI decision engine: structured inputs -> validated Plan (local model).

Standalone from the suggest proposal flow (they share llm.py and models);
outputs the pipeline artifact output/plans/plan.json.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TypeVar

from walkie import clock, config
from walkie.ai.prompt import SYSTEM_PROMPT, build_user_prompt
from walkie.llm import complete_json, extract_json
from walkie.log import get_logger
from walkie.models import (
    Daylight,
    Intensity,
    LocationType,
    Plan,
    Proposal,
    UserPlan,
    Weather,
)
from walkie.storage import read_json, write_json
from walkie.weather import weather_fingerprint, weather_line

log = get_logger("plan")

LlmFn = Callable[[str], dict | None]

PLAN_MIN_HOUR = 6
PLAN_MAX_HOUR = 21
PLAN_MIN_DURATION = 5
PLAN_MAX_DURATION = 120
FALLBACK_REASON = "Kept the inputs on the table (model reply wasn't usable)."

E = TypeVar("E", bound=Enum)


def _enum_or(value: object, enum_cls: type[E], default: E) -> E:
    try:
        return enum_cls(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return default


def parse_llm_plan(text: str) -> dict | None:
    """Extract and validate the planning JSON from an LLM reply."""
    data = extract_json(text)
    if data is None:
        return None
    start = data.get("window_start")
    if not isinstance(start, str) or not clock.TIME_RE.match(start):
        return None
    hour, minute = int(start.split(":")[0]), int(start.split(":")[1])
    if hour < PLAN_MIN_HOUR or hour > PLAN_MAX_HOUR or (
        hour == PLAN_MAX_HOUR and minute > 0
    ):
        return None
    duration = data.get("duration_minutes")
    if not isinstance(duration, int) or not (
        PLAN_MIN_DURATION <= duration <= PLAN_MAX_DURATION
    ):
        return None
    location_type = data.get("location_type")
    if location_type is not None and location_type not in (
        member.value for member in LocationType
    ):
        return None
    intensity = data.get("intensity")
    if intensity is not None and intensity not in (
        member.value for member in Intensity
    ):
        return None
    return data


def call_llm(user_prompt: str) -> dict | None:
    """Best-effort structured reply from the local model."""
    return complete_json(user_prompt, system=SYSTEM_PROMPT)


def make_plan(
    base_plan: UserPlan,
    weather: Weather | None,
    daylight: Daylight | None,
    proposal: Proposal | None,
    llm: dict | None,
    now: datetime | None = None,
) -> Plan:
    """Assemble the plan; falls back to inputs when the LLM fails."""
    now = now or clock.now()
    llm = llm or {}

    window_start = llm.get("window_start") or (
        proposal.suggested_time if proposal else base_plan.preferred_time
    )
    hour, minute = int(window_start.split(":")[0]), int(window_start.split(":")[1])
    duration = int(
        llm.get("duration_minutes")
        or (proposal.duration_minutes if proposal else base_plan.duration_minutes)
    )
    fallback_location = (
        proposal.location_type if proposal else base_plan.location_type
    )
    location_type = _enum_or(
        llm.get("location_type"), LocationType, fallback_location
    )
    fallback_intensity = proposal.intensity if proposal else base_plan.intensity
    intensity = _enum_or(llm.get("intensity"), Intensity, fallback_intensity)
    reason = str(llm.get("reason") or FALLBACK_REASON)
    window_end = (
        datetime.strptime(window_start, "%H:%M") + timedelta(minutes=duration)
    ).strftime("%H:%M")

    return Plan(
        for_date=now.date().isoformat(),
        window_start=f"{hour:02d}:{minute:02d}",
        window_end=window_end,
        duration_minutes=duration,
        location_type=location_type,
        intensity=intensity,
        area=base_plan.area,
        sunrise=daylight.sunrise if daylight else None,
        sunset=daylight.sunset if daylight else None,
        daylight_minutes=daylight.daylight_minutes if daylight else 0,
        weather_summary=weather_line(weather),
        weather_fingerprint=weather_fingerprint(weather),
        reason=str(reason),
        route_notes=str(llm.get("route_notes") or ""),
        source="llm" if llm else "fallback",
        created_at=now.isoformat(timespec="seconds"),
    )


def plan_is_valid(plan: Plan, weather: Weather | None, now: datetime) -> bool:
    """Reuse only today's plan with unchanged conditions."""
    if plan.for_date != now.date().isoformat():
        return False
    return plan.weather_fingerprint == weather_fingerprint(weather)


def ensure_plan(
    base_plan: UserPlan,
    weather: Weather | None,
    daylight: Daylight | None,
    proposal: Proposal | None = None,
    now: datetime | None = None,
    force: bool = False,
    plan_path: Path = config.PLAN_PATH,
    llm_fn: LlmFn | None = None,
) -> Plan:
    """Reuse today's valid plan, or generate a fresh one."""
    now = now or clock.now()
    existing_data = read_json(plan_path)
    existing = Plan.from_dict(existing_data) if existing_data else None
    if existing and not force and plan_is_valid(existing, weather, now):
        log.info("Reusing today's plan.")
        return existing
    llm_fn = llm_fn or call_llm
    llm = llm_fn(build_user_prompt(base_plan, weather, daylight, proposal))
    plan = make_plan(base_plan, weather, daylight, proposal, llm, now)
    write_json(plan_path, plan.to_dict())
    log.info(
        f"Plan written: {plan.window_start}-{plan.window_end} "
        f"({plan.duration_minutes} min, {plan.location_type.value}) — "
        f"{plan.reason}"
    )
    return plan
