"""`walkie go` support: fill whatever setup is missing, in order.

Called by `walkie go` (and a bare `walkie`) before the pipeline runs.
Each step is a no-op when already satisfied, so the same command works
on a fresh clone and on an ordinary day:

1. config/settings.yaml exists (copied from the example when absent)
2. a real start point and the region's OSM extract are configured
3. config/user_plan.json exists (opens the setup wizard when not)

Only step 1 is pure local file work; step 2 downloads on first run and
step 3 opens a GUI window — that is the price of a true one-command
first run.
"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Callable
from pathlib import Path

from walkie import config, region
from walkie.log import get_logger

log = get_logger("go")

EXAMPLE_SETTINGS = config.CONFIG_DIR / "settings.example.yaml"


def ensure_settings_file(
    settings_path: Path = config.SETTINGS_PATH,
    example_path: Path = EXAMPLE_SETTINGS,
) -> bool:
    """Create settings.yaml from the example when absent; True when copied."""
    if settings_path.exists():
        return False
    if not example_path.exists():
        raise config.ConfigError(
            f"{settings_path} and {example_path} are both missing — "
            "re-clone walkie"
        )
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(example_path, settings_path)
    log.info(f"Created {settings_path} from the example")
    return True


def needs_region(settings_path: Path = config.SETTINGS_PATH) -> bool:
    """True when the start point or the OSM extract is missing/unusable."""
    if not settings_path.exists():
        return True
    try:
        settings = config.load_settings(settings_path)
    except config.ConfigError:
        return True  # example (0, 0) placeholders, or an unreadable file
    return settings.pbf is None or not settings.pbf.exists()


def ensure_region(settings_path: Path = config.SETTINGS_PATH) -> None:
    """Detect location and fetch the OSM extract; no-op when already set."""
    if not needs_region(settings_path):
        return
    log.info("Setting up your map region (first run only — downloads once)")
    region.execute(argparse.Namespace(lat=None, lon=None, name=None, dry_run=False))


def ensure_user_plan(
    run_wizard: Callable[[], None] | None = None,
    plan_path: Path = config.USER_PLAN_PATH,
) -> None:
    """Open the wizard when walk preferences are missing.

    A wizard that is closed without saving aborts `go` with a remedy
    instead of failing later inside the pipeline.
    """
    try:
        config.load_user_plan(plan_path)
        return
    except config.ConfigError:
        pass
    log.info("No walk preferences yet — opening the setup wizard")
    if run_wizard is None:
        from walkie.ui.wizard import run_setup

        run_wizard = run_setup
    try:
        run_wizard()
    except ImportError as exc:
        raise config.ConfigError(
            f"setup wizard unavailable ({exc}) — run: make wizard"
        ) from exc
    try:
        config.load_user_plan(plan_path)
    except config.ConfigError as exc:
        raise config.ConfigError(
            "setup not finished — run: walkie wizard when you have a minute"
        ) from exc


def prepare(
    settings_path: Path = config.SETTINGS_PATH,
    plan_path: Path = config.USER_PLAN_PATH,
    run_wizard: Callable[[], None] | None = None,
) -> None:
    """Run every gap-filling step in order; raises ConfigError/RegionError."""
    ensure_settings_file(settings_path)
    ensure_region(settings_path)
    ensure_user_plan(run_wizard, plan_path)
