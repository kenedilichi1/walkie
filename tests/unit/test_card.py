from pathlib import Path

from walkie.card import build_card, write_card
from walkie.models import Intensity, LocationType, Plan

FIXTURE = Path(__file__).parent.parent / "fixtures" / "square_loop.gpx"


def _plan(**overrides) -> Plan:
    base = {
        "for_date": "2026-10-07",
        "window_start": "16:30",
        "window_end": "17:00",
        "duration_minutes": 30,
        "location_type": LocationType.SHADE,
        "intensity": Intensity.MODERATE,
        "area": "Riverside",
        "weather_summary": "light rain",
        "reason": "rain holding off until evening",
    }
    base.update(overrides)
    return Plan(**base)


def test_build_card_is_html_with_plan_details():
    html = build_card(_plan())
    assert html.startswith("<!doctype html>")
    assert "16:30" in html and "17:00" in html
    assert "30 min" in html
    assert "Riverside" in html
    assert "light rain" in html
    assert "rain holding off until evening" in html


def test_build_card_omits_empty_fields():
    html = build_card(_plan(area="", weather_summary="", reason=""))
    assert "Riverside" not in html
    assert "light rain" not in html
    assert "<th>Area</th>" not in html
    assert "<th>Weather</th>" not in html


def test_build_card_includes_distance_from_gpx():
    html = build_card(_plan(), gpx_path=FIXTURE)
    # the fixture is a 400 m square
    assert "0.4 km" in html
    assert "3 turns" in html


def test_build_card_missing_gpx_omits_distance():
    html = build_card(_plan(), gpx_path=Path("/nope/missing.gpx"))
    assert "Distance" not in html


def test_build_card_without_plan_says_so():
    html = build_card(None)
    assert "No walk planned yet" in html


def test_write_card_returns_path_and_writes(tmp_path):
    out = tmp_path / "card.html"
    result = write_card(_plan(), out_path=out)
    assert result == out
    assert out.exists()
    assert "Riverside" in out.read_text(encoding="utf-8")


def test_build_card_escapes_user_text():
    html = build_card(_plan(area="<script>alert(1)</script>"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
