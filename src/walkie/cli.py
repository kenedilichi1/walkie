"""walkie command line — the only module that parses argv and exits.

    walkie wizard                     one-time setup wizard
    walkie region [--dry-run ...]     detect location, fetch OSM extract
    walkie suggest [--edit|--force]   build today's walk proposal
    walkie plan [--force-new]         build today's plan (decision engine)
    walkie remind                     fire due reminders once
    walkie daemon                     loop reminder checks until approved
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from walkie import config, region
from walkie.log import get_logger, setup

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
    return parser


def cmd_wizard(args: argparse.Namespace) -> None:
    from walkie.ui.wizard import run_setup

    run_setup()


def cmd_region(args: argparse.Namespace) -> None:
    region.execute(args)


def cmd_suggest(args: argparse.Namespace) -> None:
    from walkie.models import TodayPlan
    from walkie.storage import read_json
    from walkie.suggest.proposals import ensure_proposal
    from walkie.suggest.reminders import load_weather

    base_plan = config.load_user_plan()
    weather = load_weather()

    if args.edit:
        from walkie.ui.adjust_dialog import open_adjust_dialog

        proposal = ensure_proposal(base_plan, weather)
        existing_data = read_json(config.TODAY_PLAN_PATH)
        existing = TodayPlan.from_dict(existing_data) if existing_data else None
        if open_adjust_dialog(proposal, existing):
            log.info("Edited plan saved to output/today_plan.json")
        return

    proposal = ensure_proposal(base_plan, weather, force=args.force_new)
    if config.TODAY_PLAN_PATH.exists():
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
    from walkie.storage import read_json
    from walkie.weather import refresh_from_settings

    settings = config.load_settings()
    base_plan = config.load_user_plan()
    weather = refresh_from_settings(settings)
    daylight = daylight_for(
        settings.lat, settings.lon, settings.timezone, on=clock.now().date()
    )
    proposal = None
    proposal_data = read_json(config.PROPOSAL_PATH)
    if proposal_data:
        candidate = Proposal.from_dict(proposal_data)
        if candidate.for_date == clock.now().date().isoformat():
            proposal = candidate
    ensure_plan(
        base_plan, weather, daylight, proposal, force=args.force_new
    )


def cmd_remind(args: argparse.Namespace) -> None:
    from walkie.suggest.reminders import check_reminders

    for action in check_reminders():
        log.info(action)


def cmd_daemon(args: argparse.Namespace) -> None:
    from walkie.suggest.reminders import run_daemon

    run_daemon()


HANDLERS: dict[str, Callable[[argparse.Namespace], None]] = {
    "wizard": cmd_wizard,
    "region": cmd_region,
    "suggest": cmd_suggest,
    "plan": cmd_plan,
    "remind": cmd_remind,
    "daemon": cmd_daemon,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; exit codes live only here (0 ok, 1 error, 130 INT)."""
    setup()
    args = build_parser().parse_args(argv)
    try:
        HANDLERS[args.command](args)
    except (config.ConfigError, region.RegionError) as exc:
        log.error(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
