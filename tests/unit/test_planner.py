import json
from datetime import datetime

from walkie.ai import planner
from walkie.models import (
    Daylight,
    Intensity,
    LocationType,
    Plan,
    Proposal,
    UserPlan,
    Weather,
)

NOW = datetime.fromisoformat("2026-10-07T09:00")
DAYLIGHT = Daylight(
    for_date="2026-10-07",
    sunrise="06:14",
    sunset="18:15",
    daylight_minutes=721,
)


def test_parse_llm_plan_valid():
    text = (
        'thinking... {"window_start":"17:00","duration_minutes":45,'
        '"location_type":"shade","intensity":"moderate",'
        '"reason":"rain at noon","route_notes":"stay near trees"} done'
    )
    data = planner.parse_llm_plan(text)
    assert data["window_start"] == "17:00"
    assert data["duration_minutes"] == 45


def test_parse_llm_plan_rejects_garbage():
    assert planner.parse_llm_plan("no json here") is None
    assert planner.parse_llm_plan('{"window_start":"05:59","duration_minutes":30}') is None
    assert planner.parse_llm_plan('{"window_start":"21:01","duration_minutes":30}') is None
    assert planner.parse_llm_plan('{"window_start":"12:00","duration_minutes":4}') is None
    assert planner.parse_llm_plan('{"window_start":"12:00","duration_minutes":121}') is None
    assert planner.parse_llm_plan('{"window_start":"12:00","duration_minutes":30,'
                                  '"location_type":"beach"}') is None
    assert planner.parse_llm_plan('{"window_start":"12:00","duration_minutes":30,'
                                  '"intensity":"extreme"}') is None


def test_mock_inputs_produce_clean_json():
    """Spec test: mock inputs -> validated LLM reply -> clean JSON plan."""
    llm = {
        "window_start": "17:00",
        "duration_minutes": 45,
        "location_type": "sun",
        "intensity": "brisk",
        "reason": "rain at noon, sun after",
        "route_notes": "ridge loop",
    }
    weather = Weather(
        summary="slight rain", temperature_2m=25.0, precipitation_probability_max=70
    )
    plan = planner.make_plan(
        UserPlan(preferred_time="16:30"), weather, DAYLIGHT, None, llm, NOW
    )
    assert plan.window_start == "17:00"
    assert plan.window_end == "17:45"  # computed, not trusted from the model
    assert plan.location_type is LocationType.SUN
    assert plan.intensity is Intensity.BRISK
    assert plan.source == "llm"
    assert plan.for_date == "2026-10-07"
    assert plan.daylight_minutes == 721

    # the full record survives a JSON roundtrip untouched
    text = json.dumps(plan.to_dict(), indent=2)
    assert Plan.from_dict(json.loads(text)) == plan
    json.loads(text)  # explicitly: valid JSON out


def test_make_plan_falls_back_without_llm():
    plan = planner.make_plan(
        UserPlan(preferred_time="16:30", duration_minutes=30),
        None,
        DAYLIGHT,
        None,
        None,
        NOW,
    )
    assert plan.window_start == "16:30"
    assert plan.window_end == "17:00"
    assert plan.duration_minutes == 30
    assert plan.source == "fallback"
    assert plan.reason == planner.FALLBACK_REASON


def test_make_plan_prefers_proposal_window_when_llm_fails():
    proposal = Proposal(suggested_time="17:30", duration_minutes=60)
    plan = planner.make_plan(
        UserPlan(), None, DAYLIGHT, proposal, None, NOW
    )
    assert plan.window_start == "17:30"
    assert plan.duration_minutes == 60


def test_ensure_plan_reuses_regenerates_and_forces(tmp_path):
    plan_path = tmp_path / "plan.json"
    calls = []

    def llm_fn(prompt):
        calls.append(prompt)
        return {"window_start": "17:00", "duration_minutes": 45,
                "reason": "because rain"}

    base = UserPlan(preferred_time="16:30")
    first = planner.ensure_plan(base, None, DAYLIGHT, now=NOW,
                                plan_path=plan_path, llm_fn=llm_fn)
    assert first.window_start == "17:00"
    reused = planner.ensure_plan(base, None, DAYLIGHT, now=NOW,
                                 plan_path=plan_path, llm_fn=llm_fn)
    assert reused.created_at == first.created_at
    assert len(calls) == 1

    # weather changed -> fingerprint mismatch -> regenerate
    rain = Weather(summary="slight rain", temperature_2m=25.0,
                   precipitation_probability_max=70)
    planner.ensure_plan(base, rain, DAYLIGHT, now=NOW,
                        plan_path=plan_path, llm_fn=llm_fn)
    assert len(calls) == 2

    planner.ensure_plan(base, rain, DAYLIGHT, now=NOW, force=True,
                        plan_path=plan_path, llm_fn=llm_fn)
    assert len(calls) == 3


def test_ensure_plan_regenerates_on_new_day(tmp_path):
    plan_path = tmp_path / "plan.json"
    calls = []

    def llm_fn(prompt):
        calls.append(prompt)
        return {"window_start": "17:00", "duration_minutes": 45, "reason": "x"}

    base = UserPlan()
    planner.ensure_plan(base, None, DAYLIGHT, now=NOW,
                        plan_path=plan_path, llm_fn=llm_fn)
    planner.ensure_plan(base, None, DAYLIGHT,
                        now=datetime.fromisoformat("2026-10-08T09:00"),
                        plan_path=plan_path, llm_fn=llm_fn)
    assert len(calls) == 2


def test_call_llm_passes_system_prompt(monkeypatch):
    captured = {}

    def fake_complete_json(prompt, **kwargs):
        captured.update(kwargs)
        captured["prompt"] = prompt
        return {"window_start": "17:00"}

    monkeypatch.setattr(planner, "complete_json", fake_complete_json)
    result = planner.call_llm("structured inputs here")
    assert result == {"window_start": "17:00"}
    assert captured["system"] == planner.SYSTEM_PROMPT
    assert captured["prompt"] == "structured inputs here"
