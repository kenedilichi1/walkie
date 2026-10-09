"""Shareable walk card: one self-contained HTML page you can screenshot.

No image libraries — the card is plain HTML the phone opens from the sync
server (or a browser) and screenshots to share. It summarises today's walk:
when, how long, how far, where, and the weather.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from walkie import config
from walkie.log import get_logger
from walkie.media.voice import parse_walk
from walkie.models import Plan

log = get_logger("card")


def _distance_line(gpx_path: Path) -> str:
    """Rough distance/turn summary from the route, or '' when unavailable."""
    try:
        walk = parse_walk(gpx_path)
    except Exception:  # noqa: BLE001 - a missing/odd GPX just omits the line
        return ""
    km = walk.total_meters / 1000
    turns = len(walk.turns)
    return f"{km:.1f} km loop, {turns} turn{'s' if turns != 1 else ''}"


def build_card(plan: Plan | None, gpx_path: Path | None = None) -> str:
    """Render the walk card as HTML; a small card when there's no plan yet."""
    if plan is None:
        body = "<p>No walk planned yet.</p>"
    else:
        rows = [
            ("When", f"{plan.window_start} – {plan.window_end}"),
            ("Duration", f"{plan.duration_minutes} min"),
            ("Route", plan.location_type.value),
            ("Pace", plan.intensity.value),
        ]
        if plan.area:
            rows.append(("Area", plan.area))
        if plan.weather_summary:
            rows.append(("Weather", plan.weather_summary))
        if gpx_path is not None:
            distance = _distance_line(gpx_path)
            if distance:
                rows.append(("Distance", distance))
        cells = "".join(
            f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
            for label, value in rows
        )
        body = f"<table>{cells}</table>"
        if plan.reason:
            body += f'<p class="reason">{escape(plan.reason)}</p>'
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>walkie</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;background:#0e1116;color:#e7ecf3;"
        "display:flex;justify-content:center;margin:0;padding:24px}"
        ".card{background:#161b22;border:1px solid #30363d;border-radius:16px;"
        "padding:28px;max-width:360px;width:100%}"
        "h1{font-size:20px;margin:0 0 4px}"
        ".sub{color:#8b949e;font-size:13px;margin:0 0 20px}"
        "table{width:100%;border-collapse:collapse}"
        "th{text-align:left;color:#8b949e;font-weight:500;padding:8px 0;"
        "font-size:14px}"
        "td{text-align:right;padding:8px 0;font-size:15px}"
        "tr+tr th,tr+tr td{border-top:1px solid #21262d}"
        ".reason{color:#8b949e;font-size:13px;font-style:italic;margin-top:18px}"
        "</style></head><body><div class='card'>"
        "<h1>Today's walk</h1>"
        f"<p class='sub'>{escape(plan.for_date) if plan else ''}</p>"
        f"{body}</div></body></html>"
    )


def write_card(
    plan: Plan | None,
    gpx_path: Path | None = None,
    out_path: Path = config.WALK_CARD_PATH,
) -> Path:
    """Write the walk card to disk; returns the path written."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_card(plan, gpx_path), encoding="utf-8")
    log.info(f"Walk card written -> {out_path}")
    return out_path
