"""View and edit your standing walk schedule from the command line.

`walkie schedule` reads config/user_plan.json; with flags it updates the
fields you name and saves. This is the fast path for a schedule tweak —
no PyQt wizard needed. A change here invalidates today's proposal and
plan on the next run (via UserPlan.fingerprint), so the walk regenerates
around your new choice.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from walkie import clock, config, policy
from walkie.models import Intensity, LocationType, UserPlan


class ScheduleError(config.ConfigError):
    """A schedule value the CLI was given is not usable."""


def load_current(path: Path = config.USER_PLAN_PATH) -> UserPlan:
    """Current schedule; defaults when the file is missing (pre-wizard)."""
    try:
        return config.load_user_plan(path)
    except config.ConfigError:
        return UserPlan()


def validate(plan: UserPlan) -> None:
    """Reject a schedule the app can't run with; message names the fix."""
    if clock.parse_hhmm(plan.preferred_time) is None:
        raise ScheduleError(
            f"preferred_time {plan.preferred_time!r} is not HH:MM "
            "(use e.g. --time 16:30)"
        )
    if not (
        policy.USER_MIN_DURATION
        <= plan.duration_minutes
        <= policy.USER_MAX_DURATION
    ):
        raise ScheduleError(
            f"duration {plan.duration_minutes} outside "
            f"{policy.USER_MIN_DURATION}-{policy.USER_MAX_DURATION} min"
        )


def parse_location(value: str) -> LocationType:
    try:
        return LocationType(value)
    except ValueError:
        options = ", ".join(m.value for m in LocationType)
        raise ScheduleError(f"location {value!r} not one of: {options}") from None


def parse_intensity(value: str) -> Intensity:
    try:
        return Intensity(value)
    except ValueError:
        options = ", ".join(m.value for m in Intensity)
        raise ScheduleError(f"intensity {value!r} not one of: {options}") from None


def apply_overrides(
    plan: UserPlan,
    *,
    time: str | None = None,
    duration: int | None = None,
    location: str | None = None,
    intensity: str | None = None,
    area: str | None = None,
) -> UserPlan:
    """A copy of `plan` with the given fields replaced; None means keep."""
    return replace(
        plan,
        preferred_time=plan.preferred_time if time is None else time,
        duration_minutes=(
            plan.duration_minutes if duration is None else duration
        ),
        location_type=(
            plan.location_type
            if location is None
            else parse_location(location)
        ),
        intensity=(
            plan.intensity if intensity is None else parse_intensity(intensity)
        ),
        area=plan.area if area is None else area,
    )


def save(plan: UserPlan, path: Path = config.USER_PLAN_PATH) -> UserPlan:
    """Validate then persist; keeps any existing quote, stamps created_at."""
    validate(plan)
    record = replace(plan, created_at=clock.iso_now())
    config.save_user_plan(record, path)
    return record


def describe(plan: UserPlan) -> str:
    """One-line human summary of the standing schedule."""
    parts = [
        f"{plan.preferred_time}",
        f"{plan.duration_minutes} min",
        plan.location_type.value,
        plan.intensity.value,
    ]
    if plan.area:
        parts.append(plan.area)
    return "  ".join(parts)
