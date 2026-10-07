"""Step 8: integration pipeline — chain, branches, freshness, E2E."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

import gpxpy
import pytest
from test_routing import LAT0, LON0, write_grid_pbf

from walkie import config
from walkie.media.voice import AudioSpec
from walkie.models import UserPlan
from walkie.pipeline import run
from walkie.storage import read_json, write_json

FAKE_SYNTH = lambda text: (AudioSpec(22050, 2, 1), b"\x01\x00" * 1000)  # noqa: E731


def _settings(tmp_path: Path, pbf: Path | None) -> config.Settings:
    return config.Settings(
        lat=LAT0,
        lon=LON0,
        timezone="Africa/Lagos",
        forecast_url="http://127.0.0.1:9/forecast",
        weather_cache=tmp_path / "weather.json",
        ollama_host="http://127.0.0.1:1",
        ollama_model="test-model",
        voice_model=tmp_path / "unused.onnx",
        pbf=pbf,
    )


def _today_plan(path: Path, when: str = "16:30", minutes: int = 11) -> None:
    write_json(
        path,
        {
            "for_date": date.today().isoformat(),
            "suggested_time": when,
            "duration_minutes": minutes,
        },
    )


def _run(tmp_path: Path, pbf: Path | None, *, today: bool, **kwargs):
    paths = dict(
        proposal_path=tmp_path / "proposal.json",
        plan_path=tmp_path / "plans" / "plan.json",
        today_path=tmp_path / "today_plan.json",
        state_path=tmp_path / "reminder_state.json",
        gpx_path=tmp_path / "routes" / "walk.gpx",
        audio_path=tmp_path / "audio" / "walk_audio.mp3",
        route_cache=tmp_path / "cache" / "routes",
    )
    for key in ("plan_path", "gpx_path", "audio_path"):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
    if today and not paths["today_path"].exists():
        _today_plan(paths["today_path"])
    kwargs.setdefault("llm_fn", lambda _prompt: {})
    kwargs.setdefault("load_weather_fn", lambda: None)
    kwargs.setdefault("synth", FAKE_SYNTH)
    kwargs.setdefault("base_plan", UserPlan(preferred_time="16:30", duration_minutes=30))
    return run(
        settings=_settings(tmp_path, pbf),
        **paths,
        **kwargs,
    )


def test_run_without_approval_stops_before_route_voice(tmp_path):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    actions = _run(tmp_path, pbf, today=False)
    assert any(a.startswith("proposal ") for a in actions)
    assert any(a.startswith("plan ") for a in actions)
    assert "route/voice: waiting for approval" in actions
    assert not (tmp_path / "routes" / "walk.gpx").exists()
    assert (tmp_path / "proposal.json").exists()
    assert (tmp_path / "plans" / "plan.json").exists()


def test_run_with_approval_builds_route_and_voice(tmp_path):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    actions = _run(tmp_path, pbf, today=True)
    assert "route: rebuilt" in actions
    assert "voice: rebuilt" in actions
    gpx = tmp_path / "routes" / "walk.gpx"
    assert gpx.exists()
    points = gpxpy.parse(gpx.read_text()).tracks[0].segments[0].points
    assert (points[0].latitude, points[0].longitude) == (
        points[-1].latitude,
        points[-1].longitude,
    )
    span = (points[-1].time - points[0].time).total_seconds()
    assert span == pytest.approx(11 * 60, abs=1)  # window from today_plan.json
    assert (tmp_path / "audio" / "walk_audio.mp3").stat().st_size > 0


def test_run_skips_fresh_outputs_then_force_rebuilds(tmp_path):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    _run(tmp_path, pbf, today=True)
    actions = _run(tmp_path, pbf, today=True)
    assert "route: up-to-date" in actions
    assert "voice: up-to-date" in actions
    actions = _run(tmp_path, pbf, today=True, force=True)
    assert "route: rebuilt" in actions
    assert "voice: rebuilt" in actions


def test_run_rebuilds_route_when_today_plan_edited(tmp_path):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    _run(tmp_path, pbf, today=True)
    today = tmp_path / "today_plan.json"
    future = os.stat(today).st_mtime + 10
    os.utime(today, (future, future))  # simulate an edit after the build
    actions = _run(tmp_path, pbf, today=True)
    assert "route: rebuilt" in actions
    assert "voice: rebuilt" in actions  # cascade: gpx changed


def test_run_fires_quote_notification_when_due(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "pick_quote", lambda: "Stand up from your computer.")
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    notified: list[tuple[str, str]] = []
    at_t30 = datetime.combine(date.today(), datetime.strptime("16:00", "%H:%M").time())
    actions = _run(
        tmp_path,
        pbf,
        today=False,
        now=at_t30,
        notify_fn=lambda title, message: notified.append((title, message)),
    )
    assert "reminder-30" in actions
    assert notified[0][1].startswith("Stand up from your computer.")
    state = read_json(tmp_path / "reminder_state.json")
    assert state["fired"] == [30]


def test_run_requires_pbf_when_approved(tmp_path):
    _today_plan(tmp_path / "today_plan.json")  # approved, but no extract
    with pytest.raises(config.ConfigError, match="make region"):
        _run(tmp_path, None, today=False)


def test_e2e_full_pipeline_writes_every_output(tmp_path):
    """Spec test: end-to-end run, all output/ files verified."""
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    actions = _run(tmp_path, pbf, today=True)
    outputs = [
        "proposal.json",
        "plans/plan.json",
        "today_plan.json",
        "routes/walk.gpx",
        "audio/walk_audio.mp3",
    ]
    for rel in outputs:
        assert (tmp_path / rel).exists(), f"missing {rel}"
    assert any(a.startswith("proposal ") for a in actions)
    assert any(a.startswith("plan ") for a in actions)
    assert "route: rebuilt" in actions
    assert "voice: rebuilt" in actions
    plan = read_json(tmp_path / "plans" / "plan.json")
    proposal = read_json(tmp_path / "proposal.json")
    assert plan["for_date"] == proposal["for_date"] == date.today().isoformat()
