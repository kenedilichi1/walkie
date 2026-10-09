"""Desktop notifications: native OS bridges + quote-flavoured reminder bodies.

macOS uses `osascript`, Linux uses `notify-send` (libnotify). Both are
best-effort: a missing tool, a headless session, or a denied permission just
logs a line instead of crashing the reminder. Delivery lives here;
`suggest/reminders.py` decides when/what and injects a `notify_fn`, so tests
never shell out.

Adding a platform is one entry in `_HANDLERS` (e.g. Windows via PowerShell).
"""

from __future__ import annotations

import subprocess
import sys

from walkie import config
from walkie.log import get_logger

log = get_logger("sync")

MAX_BODY = 240  # stay under desktop notification truncation limits
TIMEOUT_SECONDS = 10


def _run(argv: list[str]) -> None:
    """Run one notification command; raises on failure (the caller logs)."""
    subprocess.run(
        argv, check=True, capture_output=True, timeout=TIMEOUT_SECONDS
    )


def _macos_script(title: str, message: str) -> str:
    """AppleScript showing one notification; backslashes and quotes escaped."""

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    return f'display notification "{esc(message)}" with title "{esc(title)}"'


def _notify_macos(title: str, message: str) -> None:
    """macOS Notification Center via osascript."""
    _run(["osascript", "-e", _macos_script(title, message)])


def _notify_linux(title: str, message: str) -> None:
    """Linux desktop via notify-send (libnotify)."""
    _run(
        [
            "notify-send",
            "--app-name=walkie",
            f"--expire-time={TIMEOUT_SECONDS * 1000}",
            title,
            message,
        ]
    )


# Platform (`sys.platform`) -> best-effort notifier. Unknown platforms just
# log, so adding one later is a single line here.
_HANDLERS = {
    "darwin": _notify_macos,
    "linux": _notify_linux,
}


def send_notification(title: str, message: str) -> None:
    """Best-effort OS notification (logs when no desktop backend)."""
    handler = _HANDLERS.get(sys.platform)
    if handler is None:
        log.info(f"no notification backend for {sys.platform}: {title} — {message}")
        return
    try:
        handler(title, message)
    except Exception as exc:  # noqa: BLE001 - headless/log fallback
        log.info(f"notification unavailable ({exc}): {title} — {message}")


def with_quote(detail: str, quote: str | None = None) -> str:
    """Quote from config/quotes.txt in front of the reminder detail."""
    chosen = quote if quote is not None else config.pick_quote()
    return f"{chosen}\n{detail}"[:MAX_BODY]
