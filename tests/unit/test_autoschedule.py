from datetime import datetime
from pathlib import Path

from grid_fixture import LAT0, LON0

from walkie import autoschedule, config
from walkie.models import UserPlan


def _settings(tmp_path: Path) -> config.Settings:
    return config.Settings(
        lat=LAT0,
        lon=LON0,
        timezone="Africa/Lagos",
        forecast_url="http://127.0.0.1:9/forecast",
        weather_cache=tmp_path / "weather.json",
        ollama_host="http://127.0.0.1:1",
        ollama_model="test-model",
        voice_model=tmp_path / "unused.onnx",
        pbf=None,
    )


def _plan() -> UserPlan:
    return UserPlan(preferred_time="16:30", duration_minutes=30)


def test_build_first_walk_writes_plan(tmp_path):
    proposal = tmp_path / "proposal.json"
    plan_path = tmp_path / "plans" / "plan.json"
    plan_path.parent.mkdir(parents=True)
    now = datetime(2026, 10, 7, 9, 0)
    plan = autoschedule.build_first_walk(
        _plan(),
        now=now,
        settings=_settings(tmp_path),
        weather=None,
        llm_fn=lambda _p: {},
        proposal_path=proposal,
        plan_path=plan_path,
    )
    assert plan.for_date == "2026-10-07"
    assert plan.window_start == "16:30"
    assert plan_path.exists()
    assert proposal.exists()


def test_build_first_walk_uses_injected_llm(tmp_path):
    plan_path = tmp_path / "plans" / "plan.json"
    plan_path.parent.mkdir(parents=True)
    now = datetime(2026, 10, 7, 9, 0)

    def llm(_prompt: str) -> dict:
        return {"window_start": "17:00", "duration_minutes": 45}

    plan = autoschedule.build_first_walk(
        _plan(),
        now=now,
        settings=_settings(tmp_path),
        weather=None,
        llm_fn=llm,
        proposal_path=tmp_path / "proposal.json",
        plan_path=plan_path,
    )
    assert plan.window_start == "17:00"
    assert plan.duration_minutes == 45
    assert plan.source == "llm"


def test_summarize_mentions_window_and_duration(tmp_path):
    plan_path = tmp_path / "plans" / "plan.json"
    plan_path.parent.mkdir(parents=True)
    plan = autoschedule.build_first_walk(
        _plan(),
        now=datetime(2026, 10, 7, 9, 0),
        settings=_settings(tmp_path),
        weather=None,
        llm_fn=lambda _p: {},
        proposal_path=tmp_path / "proposal.json",
        plan_path=plan_path,
    )
    text = autoschedule.summarize(plan)
    assert "16:30" in text
    assert "30 min" in text
