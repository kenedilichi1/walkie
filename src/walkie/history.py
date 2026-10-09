"""Keep a short history of past daily plans.

When a new day's plan replaces yesterday's, the old plan is copied into
output/plans/history/plan-<date>.json so you can look back at earlier walks.
The history folder sits beside plan.json, so tests pointed at a temp plan path
stay isolated from the real output folder.
"""

from __future__ import annotations

from pathlib import Path

from walkie import config
from walkie.log import get_logger
from walkie.models import Plan
from walkie.storage import read_record, write_json

log = get_logger("history")

DEFAULT_LIMIT = 30


def history_dir_for(plan_path: Path) -> Path:
    """History lives beside plan.json, in a `history` subfolder."""
    return Path(plan_path).parent / "history"


def archive_plan(plan: Plan, plan_path: Path = config.PLAN_PATH) -> Path | None:
    """Copy a past-day plan into history; None when there's nothing to keep."""
    if not plan.for_date:
        return None
    dest = history_dir_for(plan_path) / f"plan-{plan.for_date}.json"
    write_json(dest, plan.to_dict())
    log.info(f"Kept {plan.for_date}'s plan in history.")
    return dest


def load_history(
    plan_path: Path = config.PLAN_PATH, limit: int = DEFAULT_LIMIT
) -> list[Plan]:
    """Past plans, newest day first."""
    hdir = history_dir_for(plan_path)
    if not hdir.exists():
        return []
    plans: list[Plan] = []
    for path in sorted(hdir.glob("plan-*.json"), reverse=True)[:limit]:
        plan = read_record(path, Plan.from_dict)
        if plan is not None:
            plans.append(plan)
    return plans
