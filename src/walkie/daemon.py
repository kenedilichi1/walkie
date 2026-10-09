"""Background service: keeps today's walk current without cron.

Replaces the every-minute `walkie run` spawn with one long-lived process. The
heavy geo stack (osmnx/networkx/geopandas) is imported once at start; every
pass after that is cheap because the pipeline reuses fresh outputs.

The one thing a long-lived process must not do is plan around stale settings.
When you change your schedule (`walkie schedule`) or re-run the wizard in a
*separate* process, this daemon has to notice. `ConfigStamp` watches the mtimes
of settings.yaml and user_plan.json, so the reload happens when the files
actually change — not on a blind timer.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from walkie import clock, config
from walkie.log import get_logger
from walkie.models import UserPlan

log = get_logger("daemon")

DEFAULT_CHECK_INTERVAL = 30.0
CONFIG_PATHS: tuple[Path, ...] = (config.SETTINGS_PATH, config.USER_PLAN_PATH)
PID_PATH = config.CACHE_DIR / "daemon.pid"

LABEL = "com.walkie.daemon"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "walkie.log"


class ConfigStamp:
    """Tracks mtimes of the config files; reports when any of them changed.

    Missing files count as mtime 0.0, so creating settings.yaml for the first
    time is a change like any other.
    """

    def __init__(self, paths: Sequence[Path] = CONFIG_PATHS) -> None:
        self._paths = tuple(paths)
        self._mtimes = self._read()

    def _read(self) -> dict[Path, float]:
        stamps: dict[Path, float] = {}
        for path in self._paths:
            try:
                stamps[path] = path.stat().st_mtime
            except OSError:
                stamps[path] = 0.0
        return stamps

    def changed(self) -> bool:
        """True when a file's mtime moved since the last check; re-arms itself."""
        current = self._read()
        if current == self._mtimes:
            return False
        self._mtimes = current
        return True


def _load_config() -> tuple[config.Settings, UserPlan]:
    return config.load_settings(), config.load_user_plan()


def _write_pid(pid_path: Path) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))


def _clear_pid(pid_path: Path) -> None:
    with contextlib.suppress(OSError):
        pid_path.unlink()


def stop_daemon(pid_path: Path = PID_PATH) -> bool:
    """Ask a running daemon to exit; True when a signal was sent."""
    try:
        pid = int(pid_path.read_text().strip())
    except (OSError, ValueError):
        log.info("No daemon is running.")
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        log.info(f"No daemon with pid {pid}; clearing stale pid file.")
        _clear_pid(pid_path)
        return False
    except PermissionError:
        log.error(f"Cannot signal pid {pid} (not yours).")
        return False
    log.info(f"Stopping daemon (pid {pid}).")
    return True


def _plist_content(
    python: Path, repo_root: Path, interval: float, log_path: Path
) -> str:
    """Generate the launchd plist with the real paths filled in."""
    args = "\n".join(
        f"    <string>{arg}</string>"
        for arg in (str(python), "-m", "walkie", "daemon", "--interval", f"{interval}")
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>WorkingDirectory</key>
  <string>{repo_root}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_path}</string>
  <key>StandardErrorPath</key>
  <string>{log_path}</string>
</dict>
</plist>
"""


def _launchctl(*args: str) -> bool:
    """Run launchctl; True when it exited 0."""
    cmd = ["launchctl", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        log.error("launchctl not found; this is macOS-only.")
        return False
    if result.returncode != 0:
        log.warning(
            f"launchctl {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
        return False
    return True


def install_daemon(
    *,
    interval: float = DEFAULT_CHECK_INTERVAL,
    python: Path | None = None,
    repo_root: Path | None = None,
    plist_path: Path | None = None,
    log_path: Path | None = None,
    launchctl: Callable[..., bool] | None = None,
) -> bool:
    """Write the launchd plist and register it; True on success.

    Idempotent: re-running rewrites the plist in place and reloads the agent,
    so it stays correct after moving the repo. Start it at login, keep it alive
    on crash, and it survives reboots until stopped.
    """
    python = python or Path(sys.executable)
    repo_root = repo_root or config.ROOT
    plist_path = plist_path or PLIST_PATH
    log_path = log_path or LOG_PATH
    launchctl = launchctl or _launchctl

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(_plist_content(python, repo_root, interval, log_path))
    log.info(f"Wrote {plist_path}")

    # Reload so the new plist takes effect; ignore failure if not yet loaded.
    launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if not launchctl("bootstrap", f"gui/{os.getuid()}", str(plist_path)):
        log.error("Could not register the daemon with launchd.")
        return False
    launchctl("kickstart", f"gui/{os.getuid()}/{LABEL}")
    log.info(f"Daemon installed and started. Logs: {log_path}")
    return True


def uninstall_daemon(
    *,
    plist_path: Path | None = None,
    pid_path: Path = PID_PATH,
    launchctl: Callable[..., bool] | None = None,
) -> bool:
    """Stop the agent and remove the plist + pid file; True on success."""
    plist_path = plist_path or PLIST_PATH
    launchctl = launchctl or _launchctl

    stopped = launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    removed = False
    try:
        plist_path.unlink()
        removed = True
        log.info(f"Removed {plist_path}")
    except FileNotFoundError:
        log.info("No launchd agent to remove.")
    except OSError as exc:
        log.error(f"Could not remove {plist_path}: {exc}")

    _clear_pid(pid_path)
    if stopped or removed:
        log.info("Daemon uninstalled; it will no longer start at login.")
        return True
    return False


def run_daemon(
    check_interval: float = DEFAULT_CHECK_INTERVAL,
    *,
    now_fn: Callable[[], datetime] = clock.now,
    run_fn: Callable[..., list[str]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    pid_path: Path = PID_PATH,
    config_paths: Sequence[Path] = CONFIG_PATHS,
) -> None:
    """Loop the pipeline until stopped, reloading config only when it changes.

    A single instance is enforced via a pid file so two daemons cannot double
    fire reminders. Any error in one pass is logged and the loop continues —
    a background service should not die because one run hiccuped.
    """
    from walkie.pipeline import run as pipeline_run

    run = run_fn or pipeline_run

    existing = _read_pid(pid_path)
    if existing is not None and existing != os.getpid() and _pid_alive(existing):
        log.error(
            f"Daemon already running (pid {existing}); "
            "stop it first with: walkie daemon --stop"
        )
        return

    _write_pid(pid_path)
    stamp = ConfigStamp(config_paths)
    settings, base_plan = _load_config()
    log.info(
        f"Daemon started (pid {os.getpid()}); checking every "
        f"{check_interval:.0f}s. Stop with: walkie daemon --stop"
    )

    stopping = False

    def _handle_term(_signum: object, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous = signal.signal(signal.SIGTERM, _handle_term)
    try:
        while not stopping:
            if stamp.changed():
                log.info("Settings or schedule changed; reloading.")
                settings, base_plan = _load_config()
            try:
                for action in run(now=now_fn(), settings=settings, base_plan=base_plan):
                    log.info(action)
            except (
                Exception
            ) as exc:  # noqa: BLE001 - one bad pass must not kill the loop
                log.warning(f"Pass failed ({exc}); will retry.")
            sleep_fn(check_interval)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        _clear_pid(pid_path)
        log.info("Daemon stopped.")


def _read_pid(pid_path: Path) -> int | None:
    try:
        return int(pid_path.read_text().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by someone else
    return True
