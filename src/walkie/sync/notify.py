"""Desktop notifications: plyer bridge + quote-flavoured reminder bodies.

Delivery lives here; `suggest/reminders.py` decides when/what and injects a
`notify_fn`, so tests never touch plyer.
"""

from __future__ import annotations

from walkie import config
from walkie.log import get_logger

log = get_logger("sync")

MAX_BODY = 240  # stay under desktop notification truncation limits


def send_notification(title: str, message: str) -> None:
    """Best-effort OS notification (logs when no desktop backend)."""
    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name="walkie", timeout=10)
    except Exception as exc:  # noqa: BLE001 - headless/log fallback
        log.info(f"notification unavailable ({exc}): {title} — {message}")


def with_quote(detail: str, quote: str | None = None) -> str:
    """Quote from config/quotes.txt in front of the reminder detail."""
    chosen = quote if quote is not None else config.pick_quote()
    return f"{chosen}\n{detail}"[:MAX_BODY]
