from datetime import datetime

import suggest


def test_parse_llm_json_valid():
    text = 'Here you go: {"suggested_time":"17:00","duration_minutes":45,'
    text += '"reason":"rain coming","route_notes":"stay near trees"} ok'
    result = suggest.parse_llm_json(text)
    assert result["suggested_time"] == "17:00"
    assert result["duration_minutes"] == 45


def test_parse_llm_json_rejects_garbage():
    assert suggest.parse_llm_json("no json here") is None
    assert suggest.parse_llm_json('{"suggested_time":"25:99"}') is None
    assert suggest.parse_llm_json(
        '{"suggested_time":"03:00","duration_minutes":30}'
    ) is None
    assert suggest.parse_llm_json(
        '{"suggested_time":"12:00","duration_minutes":999}'
    ) is None


def test_weather_fingerprint_stable_and_discriminating():
    base = {"summary": "rain", "temperature_2m": 26.0,
            "precipitation_probability_max": 40}
    jittered = {**base, "temperature_2m": 26.4}
    assert suggest.weather_fingerprint(base) == suggest.weather_fingerprint(jittered)
    drier = {**base, "precipitation_probability_max": 5}
    assert suggest.weather_fingerprint(base) != suggest.weather_fingerprint(drier)
    assert suggest.weather_fingerprint(None) == "unavailable"


def test_make_proposal_falls_back_without_llm():
    plan = {"preferred_time": "16:30", "duration_minutes": 30,
            "location_type": "shade", "intensity": "relaxed", "area": ""}
    proposal = suggest.make_proposal(plan, None, None)
    assert proposal["suggested_time"] == "16:30"
    assert proposal["duration_minutes"] == 30
    assert "base plan" in proposal["reason"]
    assert proposal["approve_by"].endswith("16:30")


def _proposal(when="16:30"):
    return {"suggested_time": when, "duration_minutes": 30,
            "location_type": "shade", "reason": "test",
            "approve_by": "2999-01-01T00:00",
            "weather_fingerprint": "unavailable"}


def test_check_reminders_fires_at_30_15_5_then_auto_approves(tmp_path):
    proposal_path = tmp_path / "proposal.json"
    today_path = tmp_path / "today_plan.json"
    state_path = tmp_path / "state.json"
    suggest.write_json(proposal_path, _proposal("16:30"))
    notified = []
    notify = lambda title, message: notified.append((title, message))  # noqa: E731
    paths = dict(proposal_path=proposal_path, today_path=today_path,
                 state_path=state_path)

    day = "2026-10-07"
    at_1600 = datetime.fromisoformat(f"{day}T16:00")
    assert suggest.check_reminders(at_1600, notify, **paths) == ["reminder-30"]
    assert suggest.check_reminders(datetime.fromisoformat(f"{day}T16:16"),
                                   notify, **paths) == ["reminder-15"]
    assert suggest.check_reminders(datetime.fromisoformat(f"{day}T16:26"),
                                   notify, **paths) == ["reminder-5"]
    # nobody edited -> auto-approve at walk time
    actions = suggest.check_reminders(datetime.fromisoformat(f"{day}T16:31"),
                                      notify, **paths)
    assert actions == ["auto-approved"]
    today = suggest.read_json(today_path)
    assert today["approved_by"] == "auto"
    # already resolved: no further actions
    assert suggest.check_reminders(datetime.fromisoformat(f"{day}T16:32"),
                                   notify, **paths) == []
    assert len(notified) == 4


def test_write_today_plan_records_edit(tmp_path):
    today_path = tmp_path / "today_plan.json"
    record = suggest.write_today_plan(
        _proposal(), "17:15", 45, approved_by="edit",
        now=datetime.fromisoformat("2026-10-07T15:00"),
        today_path=today_path,
    )
    assert record["suggested_time"] == "17:15"
    assert record["duration_minutes"] == 45
    assert record["approved_by"] == "edit"
    assert suggest.read_json(today_path)["duration_minutes"] == 45


def test_ensure_proposal_reuses_regenerates_and_forces(tmp_path, monkeypatch):
    proposal_path = tmp_path / "proposal.json"
    calls = []
    monkeypatch.setattr(suggest, "call_llm",
                        lambda prompt: calls.append(prompt) or {
                            "suggested_time": "17:00",
                            "duration_minutes": 40,
                            "reason": "because rain",
                        })
    plan = {"preferred_time": "16:30", "duration_minutes": 30,
            "location_type": "shade", "intensity": "relaxed", "area": ""}
    now = datetime.fromisoformat("2026-10-07T09:00")

    first = suggest.ensure_proposal(plan, None, now=now, proposal_path=proposal_path)
    assert first["suggested_time"] == "17:00"
    reused = suggest.ensure_proposal(plan, None, now=now, proposal_path=proposal_path)
    assert reused["created_at"] == first["created_at"]
    assert len(calls) == 1

    # weather changed -> fingerprint mismatch -> regenerate
    rain = {"summary": "slight rain", "temperature_2m": 25.0,
            "precipitation_probability_max": 70}
    suggest.ensure_proposal(plan, rain, now=now, proposal_path=proposal_path)
    assert len(calls) == 2

    suggest.ensure_proposal(plan, rain, now=now, force=True,
                            proposal_path=proposal_path)
    assert len(calls) == 3
