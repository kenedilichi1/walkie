"""System + user prompts for the planning model (pure functions, no I/O)."""

from __future__ import annotations

from walkie.models import Daylight, Proposal, UserPlan, Weather
from walkie.policy import (
    MAX_DURATION,
    MAX_HOUR,
    MAX_SHIFT_MINUTES,
    MIN_DURATION,
    MIN_HOUR,
)
from walkie.weather import weather_line

SYSTEM_PROMPT = (
    "You are walkie's planning engine. You decide one walking window for "
    "today from the structured inputs you receive. "
    "Reply with ONLY a JSON object — no markdown, no extra text. "
    'Schema: {"window_start":"HH:MM","duration_minutes":N,'
    '"location_type":"shade|sun|any","intensity":"relaxed|moderate|brisk",'
    '"reason":"one sentence why","route_notes":"one short routing tip"}. '
    f"Rules: window_start within {MIN_HOUR:02d}:00-{MAX_HOUR:02d}:00; "
    f"duration {MIN_DURATION}-{MAX_DURATION} min; "
    "rain chance over 30% -> location_type shade; prefer a start inside "
    f"daylight hours; shift at most {MAX_SHIFT_MINUTES} min from the "
    "preferred time."
)


def _daylight_line(daylight: Daylight | None) -> str:
    if daylight is None or daylight.sunrise is None:
        return "daylight unknown"
    return (
        f"sunrise {daylight.sunrise}, sunset {daylight.sunset}, "
        f"{daylight.daylight_minutes} min of daylight"
    )


def build_user_prompt(
    base_plan: UserPlan,
    weather: Weather | None,
    daylight: Daylight | None,
    proposal: Proposal | None = None,
) -> str:
    """Structured inputs -> one user message for the planning model."""
    preferred_time = proposal.suggested_time if proposal else base_plan.preferred_time
    preferred_duration = (
        proposal.duration_minutes if proposal else base_plan.duration_minutes
    )
    area = f", near {base_plan.area}" if base_plan.area else ""
    return (
        "Decide today's walk. Structured inputs: "
        f"preferred {preferred_time} for {preferred_duration} min, "
        f"{base_plan.location_type.value} preferred, "
        f"{base_plan.intensity.value} intensity{area}. "
        f"Weather: {weather_line(weather)}. "
        f"Daylight: {_daylight_line(daylight)}. "
        f"Proposal on the table: {preferred_time} "
        f"({proposal.reason if proposal else 'none yet'})."
    )
