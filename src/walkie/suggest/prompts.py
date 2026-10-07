"""Prompt text shared by the wizard confirmation and the daily proposal."""

from __future__ import annotations

from walkie.models import UserPlan, Weather
from walkie.weather import weather_line


def describe_plan(plan: UserPlan) -> str:
    """Plain-language plan summary used as LLM prompt and fallback reply."""
    parts = [f"{plan.duration_minutes} min at {plan.preferred_time}"]
    if plan.area:
        parts.append(f"near {plan.area}")
    parts.append(f"{plan.location_type.value} preferred")
    parts.append(f"{plan.intensity.value} intensity")
    return ", ".join(parts)


def build_confirmation_prompt(plan: UserPlan) -> str:
    return (
        "Confirm a walking plan with the user. Reply with exactly ONE "
        "sentence (max 25 words): summarize the plan and ask 'sound good?' "
        "in a friendly casual tone. No lists, no extra text. "
        f"Plan: {describe_plan(plan)}."
    )


def build_prompt(plan: UserPlan, weather: Weather | None) -> str:
    area = f", near {plan.area}" if plan.area else ""
    return (
        "Plan one walk today. Base plan: "
        f"{plan.duration_minutes} min at {plan.preferred_time}, "
        f"{plan.location_type.value} preferred, "
        f"{plan.intensity.value} intensity{area}. "
        f"Today's weather: {weather_line(weather)}. "
        "Rules: rain chance over 30% -> keep shade; shift start by at most "
        "60 min to dodge bad weather; time must stay within 06:00-21:00; "
        "duration 5-120 min. "
        'Reply with ONLY a JSON object: {"suggested_time":"HH:MM",'
        '"duration_minutes":N,"reason":"one sentence why",'
        '"route_notes":"one short routing tip"}. No other text.'
    )
