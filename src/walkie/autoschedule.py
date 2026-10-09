"""Generate your first walk right after the setup wizard saves.

The wizard used to stop at "your plan is saved" and leave the first walk
to the next `walkie run`. This runs the suggest+plan steps immediately so
setup ends with a concrete walk you can look at. It is best-effort: with
the model or weather offline it still produces a plan (falling back to
your own schedule), so setup never blocks on a network call.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from walkie import clock, config
from walkie.ai.planner import ensure_plan
from walkie.daylight import daylight_for
from walkie.log import get_logger
from walkie.models import Plan, UserPlan, Weather
from walkie.suggest.proposals import LlmFn, ensure_proposal
from walkie.suggest.reminders import load_weather

log = get_logger("autoschedule")


def build_first_walk(
    base_plan: UserPlan,
    *,
    now: datetime | None = None,
    settings: config.Settings | None = None,
    weather: Weather | None = None,
    llm_fn: LlmFn | None = None,
    proposal_path: Path = config.PROPOSAL_PATH,
    plan_path: Path = config.PLAN_PATH,
) -> Plan:
    """Run suggest+plan once for a freshly saved schedule; returns the Plan.

    Reuses the pipeline's ensure_proposal/ensure_plan, so the first walk
    obeys the same validators and fallbacks as every later run.
    """
    now = now or clock.now()
    settings = settings or config.load_settings()
    if weather is None:
        weather = load_weather()
    proposal = ensure_proposal(
        base_plan, weather, now, force=False,
        proposal_path=proposal_path, llm_fn=llm_fn,
    )
    daylight = daylight_for(
        settings.lat, settings.lon, settings.timezone, on=now.date()
    )
    plan = ensure_plan(
        base_plan, weather, daylight, proposal, now, force=False,
        plan_path=plan_path, llm_fn=llm_fn,
    )
    log.info(
        f"First walk planned: {plan.window_start}-{plan.window_end} "
        f"({plan.duration_minutes} min)"
    )
    return plan


def summarize(plan: Plan) -> str:
    """One-line description of the first walk for the wizard's final dialog."""
    return (
        f"Today's walk: {plan.window_start}-{plan.window_end} "
        f"({plan.duration_minutes} min, {plan.location_type.value})."
    )
