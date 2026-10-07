"""Proposal generation, validation, and persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from walkie import clock, config
from walkie.llm import complete_json, extract_json
from walkie.log import get_logger
from walkie.models import Proposal, UserPlan, Weather
from walkie.storage import read_json, write_json
from walkie.suggest.prompts import build_prompt
from walkie.weather import weather_fingerprint, weather_line

log = get_logger("suggest")

LlmFn = Callable[[str], dict | None]


def parse_llm_json(text: str) -> dict | None:
    """Extract and validate the JSON object from an LLM reply."""
    data = extract_json(text)
    if data is None:
        return None
    when = data.get("suggested_time")
    duration = data.get("duration_minutes")
    if not isinstance(when, str) or not clock.TIME_RE.match(when):
        return None
    if not isinstance(duration, int) or not 5 <= duration <= 180:
        return None
    hour, minute = int(when.split(":")[0]), int(when.split(":")[1])
    if hour > 21 or (hour == 21 and minute > 0) or hour < 6:
        return None
    return data


def call_llm(prompt: str) -> dict | None:
    """Best-effort structured reply from the local model."""
    return complete_json(prompt)


def make_proposal(
    base_plan: UserPlan,
    weather: Weather | None,
    llm: dict | None,
    now: datetime | None = None,
) -> Proposal:
    """Assemble the proposal; falls back to base prefs when the LLM fails."""
    now = now or clock.now()
    llm = llm or {}
    when = llm.get("suggested_time") or base_plan.preferred_time
    duration = llm.get("duration_minutes") or base_plan.duration_minutes
    hour, minute = int(when.split(":")[0]), int(when.split(":")[1])
    reason = llm.get("reason") or (
        "Kept your base plan (model reply wasn't usable)."
    )
    approve_by = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return Proposal(
        suggested_time=f"{hour:02d}:{minute:02d}",
        duration_minutes=int(duration),
        location_type=base_plan.location_type,
        intensity=base_plan.intensity,
        area=base_plan.area,
        weather_summary=weather_line(weather),
        weather_fingerprint=weather_fingerprint(weather),
        reason=str(reason),
        route_notes=str(llm.get("route_notes") or ""),
        created_at=now.isoformat(timespec="seconds"),
        approve_by=approve_by.isoformat(timespec="minutes"),
        for_date=now.date().isoformat(),
    )


def proposal_is_valid(
    proposal: Proposal, weather: Weather | None, now: datetime
) -> bool:
    """Reuse only today's proposal with unchanged conditions.

    Deliberately ignores approve_by: a proposal created after its own walk
    time stays valid for the day instead of regenerating on every run.
    """
    if proposal.for_date != now.date().isoformat():
        return False
    return proposal.weather_fingerprint == weather_fingerprint(weather)


def ensure_proposal(
    base_plan: UserPlan,
    weather: Weather | None,
    now: datetime | None = None,
    force: bool = False,
    proposal_path: Path = config.PROPOSAL_PATH,
    llm_fn: LlmFn | None = None,
) -> Proposal:
    """Reuse today's valid proposal, or generate a fresh one."""
    now = now or clock.now()
    existing_data = read_json(proposal_path)
    existing = Proposal.from_dict(existing_data) if existing_data else None
    if existing and not force and proposal_is_valid(existing, weather, now):
        log.info("Reusing today's proposal.")
        return existing
    llm_fn = llm_fn or call_llm
    proposal = make_proposal(
        base_plan, weather, llm_fn(build_prompt(base_plan, weather)), now
    )
    write_json(proposal_path, proposal.to_dict())
    log.info(
        f"Proposal written: walk at {proposal.suggested_time} "
        f"({proposal.duration_minutes} min) — {proposal.reason}"
    )
    return proposal
