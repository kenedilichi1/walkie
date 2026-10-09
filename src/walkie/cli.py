"""walkie command line — the only module that parses argv and exits.

    walkie wizard                     one-time setup wizard
    walkie region [--dry-run ...]     detect location, fetch OSM extract
    walkie suggest [--edit|--force]   build today's walk proposal
    walkie plan [--force-new]         build today's plan (decision engine)
    walkie route [--minutes N]        build today's walking loop -> walk.gpx
    walkie voice [--gpx PATH]         narrate route turns -> walk_audio.mp3
    walkie remind                     fire due reminders once
    walkie daemon                     loop reminder checks until approved
    walkie run [--force]              full pipeline (cron entry point)
    walkie serve [--port N]           serve today's files to your phone (LAN)
    walkie history [--limit N]        look back at past days' plans
    walkie card [--gpx PATH]          build a shareable walk card
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from walkie import config, region
from walkie.log import get_logger, setup
from walkie.media.voice import VoiceError
from walkie.routing import RouteError
from walkie.sync import SyncError

log = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="walkie",
        description="Offline-first walking planner with local AI suggestions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("wizard", help="one-time setup wizard (PyQt)")

    region_parser = sub.add_parser(
        "region", help="detect location and fetch OSM extract"
    )
    region.add_arguments(region_parser)

    suggest_parser = sub.add_parser(
        "suggest", help="build today's walk proposal"
    )
    suggest_parser.add_argument(
        "--edit", action="store_true", help="open the quick-adjust dialog"
    )
    suggest_parser.add_argument(
        "--force-new", action="store_true",
        help="regenerate the proposal even if still valid",
    )

    plan_parser = sub.add_parser(
        "plan", help="build today's plan (AI decision engine)"
    )
    plan_parser.add_argument(
        "--force-new", action="store_true",
        help="regenerate the plan even if still valid",
    )

    sub.add_parser("remind", help="fire due reminders once, then exit")
    sub.add_parser("daemon", help="loop reminder checks until approved")

    route_parser = sub.add_parser(
        "route", help="build today's walking loop -> output/routes/walk.gpx"
    )
    route_parser.add_argument(
        "--minutes", type=int,
        help="loop duration in minutes (default: today's plan)",
    )
    route_parser.add_argument(
        "--refresh", action="store_true",
        help="re-scan the OSM extract (ignore the street-graph cache)",
    )

    voice_parser = sub.add_parser(
        "voice", help="narrate route turns -> output/audio/walk_audio.mp3"
    )
    voice_parser.add_argument(
        "--gpx", type=Path, default=config.DEFAULT_WALK_GPX,
        help="GPX track to narrate (default: output/routes/walk.gpx)",
    )

    serve_parser = sub.add_parser(
        "serve", help="LAN server: phone downloads today's files"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8000,
        help="port to listen on (default: 8000)",
    )

    run_parser = sub.add_parser(
        "run", help="full pipeline: suggest -> plan -> remind -> route -> voice"
    )
    run_parser.add_argument(
        "--force", action="store_true",
        help="regenerate proposal, plan, route and voice even if fresh",
    )

    history_parser = sub.add_parser(
        "history", help="look back at past days' plans"
    )
    history_parser.add_argument(
        "--limit", type=int, default=30,
        help="how many past days to show (default: 30)",
    )

    card_parser = sub.add_parser(
        "card", help="build a shareable card of today's walk -> output/card.html"
    )
    card_parser.add_argument(
        "--gpx", type=Path, default=config.DEFAULT_WALK_GPX,
        help="route to measure for the card (default: output/routes/walk.gpx)",
    )
    return parser


def cmd_wizard(args: argparse.Namespace) -> None:
    from walkie.ui.wizard import run_setup

    run_setup()


def cmd_region(args: argparse.Namespace) -> None:
    region.execute(args)


def cmd_suggest(args: argparse.Namespace) -> None:
    from walkie.suggest.proposals import ensure_proposal
    from walkie.suggest.reminders import load_weather, read_todays_walk

    base_plan = config.load_user_plan()
    weather = load_weather()

    if args.edit:
        from walkie.ui.adjust_dialog import open_adjust_dialog

        proposal = ensure_proposal(base_plan, weather)
        existing = read_todays_walk(config.TODAY_PLAN_PATH)
        if open_adjust_dialog(proposal, existing):
            log.info("Edited plan saved to output/today_plan.json")
        return

    proposal = ensure_proposal(base_plan, weather, force=args.force_new)
    if read_todays_walk(config.TODAY_PLAN_PATH) is not None:
        log.info("Today's walk is already approved — see output/today_plan.json")
    else:
        log.info(
            f"Edit before {proposal.suggested_time}: "
            "walkie suggest --edit (or wait for auto-approve)"
        )


def cmd_plan(args: argparse.Namespace) -> None:
    from walkie import clock
    from walkie.ai.planner import ensure_plan
    from walkie.daylight import daylight_for
    from walkie.models import Proposal
    from walkie.storage import read_record
    from walkie.weather import refresh_from_settings

    settings = config.load_settings()
    base_plan = config.load_user_plan()
    weather = refresh_from_settings(settings)
    daylight = daylight_for(
        settings.lat, settings.lon, settings.timezone, on=clock.now().date()
    )
    candidate = read_record(config.PROPOSAL_PATH, Proposal.from_dict)
    proposal = (
        candidate
        if candidate is not None and candidate.for_date == clock.today_iso()
        else None
    )
    ensure_plan(
        base_plan, weather, daylight, proposal, force=args.force_new
    )


def cmd_route(args: argparse.Namespace) -> None:
    from walkie.routing.builder import build_route

    settings = config.load_settings()
    if settings.pbf is None:
        raise config.ConfigError("no OSM extract configured — run: make region")
    build_route(
        settings.pbf,
        settings.lat,
        settings.lon,
        settings.timezone,
        minutes=args.minutes,
        refresh=args.refresh,
    )


def cmd_voice(args: argparse.Namespace) -> None:
    from walkie.media.voice import build_walk_audio
    from walkie.models import Plan
    from walkie.storage import read_record

    settings = config.load_settings()
    plan = read_record(config.PLAN_PATH, Plan.from_dict)
    build_walk_audio(args.gpx, voice_model=settings.voice_model, plan=plan)


def cmd_remind(args: argparse.Namespace) -> None:
    from walkie.suggest.reminders import check_reminders

    for action in check_reminders():
        log.info(action)


def cmd_daemon(args: argparse.Namespace) -> None:
    from walkie.suggest.reminders import run_daemon

    run_daemon()


def cmd_serve(args: argparse.Namespace) -> None:
    from walkie.sync.server import serve

    serve(port=args.port)


def cmd_run(args: argparse.Namespace) -> None:
    from walkie.pipeline import run

    for action in run(force=args.force):
        log.info(action)


def cmd_history(args: argparse.Namespace) -> None:
    from walkie.history import load_history

    plans = load_history(limit=args.limit)
    if not plans:
        log.info("No past plans yet — they build up as new days arrive.")
        return
    for plan in plans:
        log.info(
            f"{plan.for_date}  {plan.window_start}-{plan.window_end}  "
            f"{plan.duration_minutes} min  {plan.location_type.value}"
        )


def cmd_card(args: argparse.Namespace) -> None:
    from walkie.card import write_card
    from walkie.models import Plan
    from walkie.storage import read_record

    plan = read_record(config.PLAN_PATH, Plan.from_dict)
    out = write_card(plan, gpx_path=args.gpx)
    log.info(f"Open it in a browser (or via walkie serve): {out}")


HANDLERS: dict[str, Callable[[argparse.Namespace], None]] = {
    "wizard": cmd_wizard,
    "region": cmd_region,
    "suggest": cmd_suggest,
    "plan": cmd_plan,
    "route": cmd_route,
    "voice": cmd_voice,
    "remind": cmd_remind,
    "daemon": cmd_daemon,
    "serve": cmd_serve,
    "run": cmd_run,
    "history": cmd_history,
    "card": cmd_card,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; exit codes live only here (0 ok, 1 error, 130 INT)."""
    setup()
    args = build_parser().parse_args(argv)
    try:
        HANDLERS[args.command](args)
    except (config.ConfigError, region.RegionError, VoiceError, RouteError,
            SyncError) as exc:
        log.error(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
