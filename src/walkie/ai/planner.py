"""AI decision engine: structured inputs -> validated Plan (local model).

Standalone from the suggest proposal flow (they share llm.py and models);
outputs the pipeline artifact output/plans/plan.json.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from walkie import clock, config, policy
from walkie.ai.prompt import SYSTEM_PROMPT, build_user_prompt
from walkie.llm import complete, extract_json
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
from walkie.policy import MAX_DURATION, MAX_HOUR, MIN_DURATION, MIN_HOUR
from walkie.storage import read_record, write_json
from walkie.weather import weather_fingerprint, weather_line

log = get_logger("plan")

LlmFn = Callable[[str], dict[str, Any] | None]

FALLBACK_REASON = "Kept the inputs on the table (model reply wasn't usable)."

E = TypeVar("E", bound=Enum)


def _enum_or(value: object, enum_cls: type[E], default: E) -> E:
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def _reply_ok(data: dict[str, Any]) -> bool:
    """Shape/range checks for one model reply — the trust boundary."""
    parsed = clock.parse_hhmm(data.get("window_start"))
    if parsed is None:
        return False
    hour, minute = parsed
    if not (MIN_HOUR <= hour <= MAX_HOUR) or (hour == MAX_HOUR and minute > 0):
        return False
    duration = data.get("duration_minutes")
    if not (isinstance(duration, int) and MIN_DURATION <= duration <= MAX_DURATION):
        return False
    location_type = data.get("location_type")
    intensity = data.get("intensity")
    location_ok = location_type is None or location_type in (
        member.value for member in LocationType
    )
    intensity_ok = intensity is None or intensity in (
        member.value for member in Intensity
    )
    return location_ok and intensity_ok


def parse_llm_plan(text: str) -> dict[str, Any] | None:
    """Extract and validate the planning JSON from an LLM reply."""
    data = extract_json(text)
    return data if data is not None and _reply_ok(data) else None


def call_llm(user_prompt: str) -> dict[str, Any] | None:
    """Best-effort structured reply; None when unreachable or unusable."""
    text = complete(user_prompt, system=SYSTEM_PROMPT)
    return parse_llm_plan(text) if text else None


def make_plan(
    base_plan: UserPlan,
    weather: Weather | None,
    daylight: Daylight | None,
    proposal: Proposal | None,
    llm: dict[str, Any] | None,
    now: datetime | None = None,
) -> Plan:
    """Assemble the plan; falls back to inputs when the LLM fails."""
    now = now or clock.now()
    llm = llm or {}

    parsed = clock.parse_first(
        llm.get("window_start"),
        proposal.suggested_time if proposal else None,
        base_plan.preferred_time,
    )
    if parsed is None:
        log.warning(
            f"Unusable walk time {base_plan.preferred_time!r}; "
            f"using {policy.DEFAULT_TIME}"
        )
        parsed = policy.DEFAULT_HHMM
    hour, minute = parsed

    preferred_duration = (
        proposal.duration_minutes if proposal else base_plan.duration_minutes
    )
    base_duration = policy.coerce_duration(preferred_duration)
    duration = policy.coerce_duration(llm.get("duration_minutes"), base_duration)

    fallback_location = (
        proposal.location_type if proposal else base_plan.location_type
    )
    location_type = _enum_or(
        llm.get("location_type"), LocationType, fallback_location
    )
    fallback_intensity = proposal.intensity if proposal else base_plan.intensity
    intensity = _enum_or(llm.get("intensity"), Intensity, fallback_intensity)
    reason = str(llm.get("reason") or FALLBACK_REASON)
    window_start = f"{hour:02d}:{minute:02d}"
    window_end = (
        datetime.combine(now.date(), time(hour, minute)) + timedelta(minutes=duration)
    ).strftime("%H:%M")

    return Plan(
        for_date=clock.today_iso(now),
        window_start=window_start,
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
        reason=reason,
        route_notes=str(llm.get("route_notes") or ""),
        source=Plan.SOURCE_LLM if llm else Plan.SOURCE_FALLBACK,
        created_at=clock.iso_now(now),
    )


def plan_is_valid(plan: Plan, weather: Weather | None, now: datetime) -> bool:
    """Reuse only today's plan with unchanged conditions."""
    if plan.for_date != clock.today_iso(now):
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
    """Reuse today's valid plan, or generate a fresh one.

    The reply from `llm_fn` is untrusted (a test fake or another caller may
    supply it), so it goes through the same checks as the default path.
    """
    now = now or clock.now()
    existing = read_record(plan_path, Plan.from_dict)
    if existing and not force and plan_is_valid(existing, weather, now):
        log.info("Reusing today's plan.")
        return existing
    llm = (llm_fn or call_llm)(build_user_prompt(base_plan, weather, daylight, proposal))
    if llm and not _reply_ok(llm):
        log.warning(f"Ignoring unusable model reply: {llm!r}")
        llm = None
    plan = make_plan(base_plan, weather, daylight, proposal, llm, now)
    write_json(plan_path, plan.to_dict())
    log.info(
        f"Plan written: {plan.window_start}-{plan.window_end} "
        f"({plan.duration_minutes} min, {plan.location_type.value}) — "
        f"{plan.reason}"
    )
    return plan
