"""Integration pipeline: suggest -> plan -> reminders -> route -> voice.

`walkie run` calls this; cron is the scheduled entry point. Every step is
idempotent (reuses today's outputs), and route/voice rebuild only when their
inputs are newer, so an every-minute cron stays cheap. Reminders run before
the approved-branch check so an auto-approve at walk time builds the route
in the same pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from walkie import clock, config
from walkie.ai.planner import ensure_plan
from walkie.daylight import daylight_for
from walkie.log import get_logger
from walkie.media.voice import Synth, build_walk_audio
from walkie.models import UserPlan, Weather
from walkie.routing.builder import build_route, resolve_walk_window
from walkie.suggest.proposals import LlmFn, ensure_proposal
from walkie.suggest.reminders import (
    NotifyFn,
    check_reminders,
    load_weather,
    read_todays_walk,
    refresh_stale_approval,
)

log = get_logger("pipeline")

LoadWeatherFn = Callable[[], Weather | None]

@dataclass(frozen=True)
class PipelinePaths:
    proposal: Path = config.PROPOSAL_PATH
    plan: Path = config.PLAN_PATH
    today: Path = config.TODAY_PLAN_PATH
    state: Path = config.REMINDER_STATE_PATH
    gpx: Path = config.DEFAULT_WALK_GPX
    audio: Path = config.WALK_AUDIO_PATH
    route_cache: Path = config.CACHE_DIR / "routes"


DEFAULT_PATHS = PipelinePaths()


def _stale(output: Path, inputs: tuple[Path, ...], force: bool) -> bool:
    """True when output must be rebuilt (missing, outdated, or forced)."""
    if force or not output.exists():
        return True
    newest = max((p.stat().st_mtime for p in inputs if p.exists()), default=0.0)
    return output.stat().st_mtime < newest


def run(
    *,
    force: bool = False,
    now: datetime | None = None,
    settings: config.Settings | None = None,
    base_plan: UserPlan | None = None,
    load_weather_fn: LoadWeatherFn | None = None,
    llm_fn: LlmFn | None = None,
    notify_fn: NotifyFn | None = None,
    synth: Synth | None = None,
    paths: PipelinePaths = DEFAULT_PATHS,
) -> list[str]:
    """Run the full chain once; returns report lines (the CLI logs them)."""
    settings = settings or config.load_settings()
    base_plan = base_plan or config.load_user_plan()
    weather = (load_weather_fn or load_weather)()

    actions: list[str] = []
    proposal = ensure_proposal(
        base_plan, weather, now, force, paths.proposal, llm_fn
    )
    actions.append(
        f"proposal {proposal.suggested_time} ({proposal.duration_minutes} min)"
    )
    daylight = daylight_for(
        settings.lat, settings.lon, settings.timezone,
        on=(now or clock.now()).date(),
    )
    plan = ensure_plan(
        base_plan, weather, daylight, proposal, now, force, paths.plan, llm_fn
    )
    actions.append(
        f"plan {plan.window_start}-{plan.window_end} ({plan.duration_minutes} min)"
    )

    # A schedule change replaces today's approval so route/voice follow.
    if refresh_stale_approval(base_plan, proposal, now, paths.today):
        actions.append("approval: refreshed for new schedule")

    # Reminders before the branch: auto-approve at walk time creates
    # today_plan.json, so route/voice build in this same pass.
    actions.extend(
        check_reminders(
            now=now,
            notify_fn=notify_fn,
            proposal_path=paths.proposal,
            today_path=paths.today,
            state_path=paths.state,
        )
    )

    # Date-aware: a leftover today_plan.json from an earlier day does not
    # count as approval, so route/voice keep waiting for today's decision.
    if read_todays_walk(paths.today, now) is not None:
        pbf = settings.pbf
        if pbf is None:
            raise config.ConfigError(
                "no OSM extract configured — run: make region"
            )
        if _stale(paths.gpx, (paths.today,), force):
            window = resolve_walk_window(
                settings.timezone,
                today_plan_path=paths.today,
                plan_path=paths.plan,
            )
            build_route(
                pbf,
                settings.lat,
                settings.lon,
                settings.timezone,
                window=window,
                cache_dir=paths.route_cache,
                out_path=paths.gpx,
            )
            actions.append("route: rebuilt")
        else:
            actions.append("route: up-to-date")
        if _stale(paths.audio, (paths.gpx,), force):
            build_walk_audio(
                paths.gpx,
                out_path=paths.audio,
                voice_model=settings.voice_model,
                synth=synth,
            )
            actions.append("voice: rebuilt")
        else:
            actions.append("voice: up-to-date")
    else:
        actions.append("route/voice: waiting for approval")

    return actions
