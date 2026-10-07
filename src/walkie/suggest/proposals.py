"""Proposal generation, validation, and persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from walkie import clock, config, policy
from walkie.llm import complete, extract_json
from walkie.log import get_logger
from walkie.models import Proposal, UserPlan, Weather
from walkie.policy import MAX_DURATION, MAX_HOUR, MIN_DURATION, MIN_HOUR
from walkie.storage import read_record, write_json
from walkie.suggest.prompts import build_prompt
from walkie.weather import weather_fingerprint, weather_line

log = get_logger("suggest")

LlmFn = Callable[[str], dict[str, Any] | None]


def _reply_ok(data: dict[str, Any]) -> bool:
    """Shape/range checks for one model reply — the trust boundary."""
    parsed = clock.parse_hhmm(data.get("suggested_time"))
    if parsed is None:
        return False
    hour, minute = parsed
    if not (MIN_HOUR <= hour <= MAX_HOUR) or (hour == MAX_HOUR and minute > 0):
        return False
    duration = data.get("duration_minutes")
    return isinstance(duration, int) and MIN_DURATION <= duration <= MAX_DURATION


def parse_llm_json(text: str) -> dict[str, Any] | None:
    """Extract and validate the JSON object from an LLM reply."""
    data = extract_json(text)
    return data if data is not None and _reply_ok(data) else None


def call_llm(prompt: str) -> dict[str, Any] | None:
    """Best-effort structured reply; None when unreachable or unusable."""
    text = complete(prompt)
    return parse_llm_json(text) if text else None


def make_proposal(
    base_plan: UserPlan,
    weather: Weather | None,
    llm: dict[str, Any] | None,
    now: datetime | None = None,
) -> Proposal:
    """Assemble the proposal; falls back to base prefs when the LLM fails."""
    now = now or clock.now()
    llm = llm or {}
    parsed = clock.parse_first(llm.get("suggested_time"), base_plan.preferred_time)
    if parsed is None:
        log.warning(
            f"Unusable walk time {base_plan.preferred_time!r}; "
            f"using {policy.DEFAULT_TIME}"
        )
        parsed = policy.DEFAULT_HHMM
    hour, minute = parsed
    base_duration = policy.coerce_duration(base_plan.duration_minutes)
    duration = policy.coerce_duration(llm.get("duration_minutes"), base_duration)
    reason = llm.get("reason") or (
        "Kept your base plan (model reply wasn't usable)."
    )
    approve_by = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return Proposal(
        suggested_time=f"{hour:02d}:{minute:02d}",
        duration_minutes=duration,
        location_type=base_plan.location_type,
        intensity=base_plan.intensity,
        area=base_plan.area,
        weather_summary=weather_line(weather),
        weather_fingerprint=weather_fingerprint(weather),
        reason=str(reason),
        route_notes=str(llm.get("route_notes") or ""),
        created_at=clock.iso_now(now),
        approve_by=approve_by.isoformat(timespec="minutes"),
        for_date=clock.today_iso(now),
    )


def proposal_is_valid(
    proposal: Proposal, weather: Weather | None, now: datetime
) -> bool:
    """Reuse only today's proposal with unchanged conditions.

    Deliberately ignores approve_by: a proposal created after its own walk
    time stays valid for the day instead of regenerating on every run.
    """
    if proposal.for_date != clock.today_iso(now):
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
    """Reuse today's valid proposal, or generate a fresh one.

    The reply from `llm_fn` is untrusted (a test fake or another caller may
    supply it), so it goes through the same checks as the default path.
    """
    now = now or clock.now()
    existing = read_record(proposal_path, Proposal.from_dict)
    if existing and not force and proposal_is_valid(existing, weather, now):
        log.info("Reusing today's proposal.")
        return existing
    llm = (llm_fn or call_llm)(build_prompt(base_plan, weather))
    if llm and not _reply_ok(llm):
        log.warning(f"Ignoring unusable model reply: {llm!r}")
        llm = None
    proposal = make_proposal(base_plan, weather, llm, now)
    write_json(proposal_path, proposal.to_dict())
    log.info(
        f"Proposal written: walk at {proposal.suggested_time} "
        f"({proposal.duration_minutes} min) — {proposal.reason}"
    )
    return proposal
