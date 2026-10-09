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
from walkie.policy import MAX_DURATION, MAX_HOUR, MIN_DURATION

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
    base = UserPlan(preferred_time="16:30", duration_minutes=30)
    data = planner.parse_llm_plan(text, base)
    assert data["window_start"] == "17:00"
    assert data["duration_minutes"] == 45
    # in-window boundaries are accepted: 20:00 +/- 60 hits 21:00 exactly
    edge = UserPlan(preferred_time="20:00", duration_minutes=120)
    assert planner.parse_llm_plan(
        f'{{"window_start":"{MAX_HOUR:02d}:00","duration_minutes":{MAX_DURATION}}}',
        edge,
    )


def test_parse_llm_plan_rejects_garbage():
    base = UserPlan(preferred_time="12:00", duration_minutes=30)
    assert planner.parse_llm_plan("no json here", base) is None
    assert planner.parse_llm_plan(
        '{"window_start":"05:59","duration_minutes":30}', base
    ) is None
    assert planner.parse_llm_plan(
        '{"window_start":"21:01","duration_minutes":30}', base
    ) is None
    assert planner.parse_llm_plan(
        '{"window_start":"12:75","duration_minutes":30}', base
    ) is None
    assert planner.parse_llm_plan(
        f'{{"window_start":"12:00","duration_minutes":{MIN_DURATION - 1}}}',
        base,
    ) is None
    assert planner.parse_llm_plan(
        f'{{"window_start":"12:00","duration_minutes":{MAX_DURATION + 1}}}',
        base,
    ) is None
    assert planner.parse_llm_plan(
        '{"window_start":"12:00","duration_minutes":30,'
        '"location_type":"beach"}',
        base,
    ) is None
    assert planner.parse_llm_plan(
        '{"window_start":"12:00","duration_minutes":30,'
        '"intensity":"extreme"}',
        base,
    ) is None


def test_parse_llm_plan_rejects_drift_outside_window():
    """12:00 +/- 60 means 11:00-13:00 — 14:00 is drift, not a nudge."""
    base = UserPlan(preferred_time="12:00", duration_minutes=30)
    assert planner.parse_llm_plan(
        '{"window_start":"14:00","duration_minutes":30}', base
    ) is None
    # the duration window is 50%-150% of 30 -> 15-45; 50 is out
    assert planner.parse_llm_plan(
        '{"window_start":"12:00","duration_minutes":50}', base
    ) is None


def test_parse_llm_plan_keeps_out_of_window_user_choice():
    """A 22:30 / 240 min anchor is untouchable: echo it or nothing."""
    base = UserPlan(preferred_time="22:30", duration_minutes=240)
    assert planner.parse_llm_plan(
        '{"window_start":"22:30","duration_minutes":240}', base
    )
    assert planner.parse_llm_plan(
        '{"window_start":"18:30","duration_minutes":60}', base
    ) is None


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


def test_make_plan_keeps_user_time_and_duration_outside_model_range():
    """A 22:30 / 240 min user plan is legal even though the model can't say it."""
    plan = planner.make_plan(
        UserPlan(preferred_time="22:30", duration_minutes=240),
        None,
        DAYLIGHT,
        None,
        None,
        NOW,
    )
    assert plan.window_start == "22:30"
    assert plan.duration_minutes == 240


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
        return {"window_start": "13:00", "duration_minutes": 45, "reason": "x"}

    base = UserPlan()
    planner.ensure_plan(base, None, DAYLIGHT, now=NOW,
                        plan_path=plan_path, llm_fn=llm_fn)
    planner.ensure_plan(base, None, DAYLIGHT,
                        now=datetime.fromisoformat("2026-10-08T09:00"),
                        plan_path=plan_path, llm_fn=llm_fn)
    assert len(calls) == 2


def test_ensure_plan_regenerates_when_schedule_changes(tmp_path):
    """A wizard change to the schedule must regenerate, same day, no --force."""
    plan_path = tmp_path / "plan.json"
    calls = []

    def llm_fn(prompt):
        calls.append(prompt)
        return {"window_start": "13:00", "duration_minutes": 30, "reason": "x"}

    old = UserPlan(preferred_time="13:00", duration_minutes=30)
    planner.ensure_plan(old, None, DAYLIGHT, now=NOW,
                        plan_path=plan_path, llm_fn=llm_fn)
    assert len(calls) == 1

    new = UserPlan(preferred_time="18:00", duration_minutes=60)
    planner.ensure_plan(new, None, DAYLIGHT, now=NOW,
                        plan_path=plan_path, llm_fn=llm_fn)
    assert len(calls) == 2


def test_ensure_plan_rejects_drift_outside_window(tmp_path):
    """A model that ignores the shift limit gets dropped, not obeyed."""
    plan_path = tmp_path / "plan.json"
    base = UserPlan(preferred_time="16:30", duration_minutes=30)
    drift = {"window_start": "18:30", "duration_minutes": 30,
             "reason": "felt like evening"}

    plan = planner.ensure_plan(
        base, None, DAYLIGHT, now=NOW, plan_path=plan_path,
        llm_fn=lambda prompt: drift,
    )
    assert plan.window_start == "16:30"
    assert plan.source == Plan.SOURCE_FALLBACK


def test_ensure_plan_echoes_out_of_window_user_choice(tmp_path):
    """A model that correctly echoes 22:30 / 240 keeps its reason."""
    plan_path = tmp_path / "plan.json"
    base = UserPlan(preferred_time="22:30", duration_minutes=240)
    echo = {"window_start": "22:30", "duration_minutes": 240,
            "reason": "late walk, keep it"}

    plan = planner.ensure_plan(
        base, None, DAYLIGHT, now=NOW, plan_path=plan_path,
        llm_fn=lambda prompt: echo,
    )
    assert plan.window_start == "22:30"
    assert plan.duration_minutes == 240
    assert plan.reason == "late walk, keep it"
    assert plan.source == Plan.SOURCE_LLM


def test_call_llm_passes_system_prompt(monkeypatch):
    captured = {}

    def fake_complete(prompt, **kwargs):
        captured.update(kwargs)
        captured["prompt"] = prompt
        return '{"window_start": "17:00", "duration_minutes": 45}'

    monkeypatch.setattr(planner, "complete", fake_complete)
    base = UserPlan(preferred_time="16:30", duration_minutes=30)
    result = planner.call_llm("structured inputs here", base)
    assert result == {"window_start": "17:00", "duration_minutes": 45}
    assert captured["system"] == planner.SYSTEM_PROMPT
    assert captured["prompt"] == "structured inputs here"


def test_call_llm_rejects_out_of_policy_reply(monkeypatch):
    """The validator runs on the production path, not only in unit tests."""
    monkeypatch.setattr(
        planner,
        "complete",
        lambda prompt, **kwargs: '{"window_start": "25:00", "duration_minutes": 45}',
    )
    base = UserPlan(preferred_time="16:30", duration_minutes=30)
    assert planner.call_llm("structured inputs here", base) is None


def test_ensure_plan_ignores_unusable_llm_reply(tmp_path):
    """A malformed reply falls back to the inputs instead of crashing."""
    plan_path = tmp_path / "plan.json"
    base = UserPlan(preferred_time="16:30", duration_minutes=30)

    def llm_fn(prompt):
        return {"window_start": "25:00", "duration_minutes": 45, "reason": "bad"}

    plan = planner.ensure_plan(
        base, None, DAYLIGHT, now=NOW, plan_path=plan_path, llm_fn=llm_fn
    )
    assert plan.window_start == "16:30"
    assert plan.duration_minutes == 30
    assert plan.source == Plan.SOURCE_FALLBACK
