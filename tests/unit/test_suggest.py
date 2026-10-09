from datetime import datetime
from types import SimpleNamespace

from walkie import config
from walkie.models import Proposal, UserPlan, Weather
from walkie.storage import read_json, write_json
from walkie.suggest import proposals, reminders


def test_parse_llm_json_valid():
    text = 'Here you go: {"suggested_time":"17:00","duration_minutes":45,'
    text += '"reason":"rain coming","route_notes":"stay near trees"} ok'
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    result = proposals.parse_llm_json(text, plan)
    assert result["suggested_time"] == "17:00"
    assert result["duration_minutes"] == 45


def test_parse_llm_json_rejects_garbage():
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    assert proposals.parse_llm_json("no json here", plan) is None
    assert proposals.parse_llm_json('{"suggested_time":"25:99"}', plan) is None
    assert proposals.parse_llm_json(
        '{"suggested_time":"03:00","duration_minutes":30}', plan
    ) is None
    assert proposals.parse_llm_json(
        '{"suggested_time":"12:00","duration_minutes":999}', plan
    ) is None


def test_parse_llm_json_rejects_drift_outside_window():
    """The model may nudge 16:30 by 60 min, not redefine it."""
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    # 18:30 is 2 h after 16:30 — outside the ±60 min window
    assert proposals.parse_llm_json(
        '{"suggested_time":"18:30","duration_minutes":30}', plan
    ) is None
    # 17:30 is exactly the edge — allowed
    assert proposals.parse_llm_json(
        '{"suggested_time":"17:30","duration_minutes":30}', plan
    )


def test_parse_llm_json_keeps_out_of_window_user_choice():
    """A 22:30 / 240 min user plan is untouchable: echo it or nothing."""
    plan = UserPlan(preferred_time="22:30", duration_minutes=240)
    # echoing the user's own values is allowed even outside the standing window
    assert proposals.parse_llm_json(
        '{"suggested_time":"22:30","duration_minutes":240}', plan
    )
    # changing them is not
    assert proposals.parse_llm_json(
        '{"suggested_time":"18:30","duration_minutes":60}', plan
    ) is None
    assert proposals.parse_llm_json(
        '{"suggested_time":"22:30","duration_minutes":60}', plan
    ) is None
    assert proposals.parse_llm_json(
        '{"suggested_time":"18:30","duration_minutes":240}', plan
    ) is None


def test_make_proposal_falls_back_without_llm():
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    proposal = proposals.make_proposal(
        plan, None, None, now=datetime.fromisoformat("2026-10-07T09:00")
    )
    assert proposal.suggested_time == "16:30"
    assert proposal.duration_minutes == 30
    assert "base plan" in proposal.reason
    assert proposal.approve_by.endswith("16:30")
    assert proposal.for_date == "2026-10-07"


def test_make_proposal_keeps_user_evening_time_and_long_duration():
    """User choices sit outside the model window but must survive fallback."""
    plan = UserPlan(preferred_time="22:30", duration_minutes=240)
    proposal = proposals.make_proposal(
        plan, None, None, now=datetime.fromisoformat("2026-10-08T20:00")
    )
    assert proposal.suggested_time == "22:30"
    assert proposal.duration_minutes == 240


def _proposal(when="16:30", for_date="2026-10-07"):
    return {
        "suggested_time": when,
        "duration_minutes": 30,
        "location_type": "shade",
        "reason": "test",
        "approve_by": f"{for_date}T{when}",
        "for_date": for_date,
        "weather_fingerprint": "unavailable",
    }


def _approved(for_date, when="16:30"):
    return Proposal.from_dict(_proposal(when, for_date=for_date)).approve(
        f"{for_date}T15:00", approved_by="auto"
    )


def test_check_reminders_fires_at_30_15_5_then_auto_approves(tmp_path):
    proposal_path = tmp_path / "proposal.json"
    today_path = tmp_path / "today_plan.json"
    state_path = tmp_path / "state.json"
    write_json(proposal_path, _proposal("16:30"))
    notified = []
    notify = lambda title, message: notified.append((title, message))  # noqa: E731
    paths = {
        "proposal_path": proposal_path,
        "today_path": today_path,
        "state_path": state_path,
    }

    day = "2026-10-07"
    at_1600 = datetime.fromisoformat(f"{day}T16:00")
    assert reminders.check_reminders(at_1600, notify, **paths) == ["reminder-30"]
    assert reminders.check_reminders(datetime.fromisoformat(f"{day}T16:16"),
                                     notify, **paths) == ["reminder-15"]
    assert reminders.check_reminders(datetime.fromisoformat(f"{day}T16:26"),
                                     notify, **paths) == ["reminder-5"]
    # nobody edited -> auto-approve at walk time
    actions = reminders.check_reminders(datetime.fromisoformat(f"{day}T16:31"),
                                        notify, **paths)
    assert actions == ["auto-approved"]
    today = read_json(today_path)
    assert today["approved_by"] == "auto"
    # already resolved: no further actions
    assert reminders.check_reminders(datetime.fromisoformat(f"{day}T16:32"),
                                     notify, **paths) == []
    assert len(notified) == 4


def test_check_reminders_ignores_proposal_from_yesterday(tmp_path):
    """B1: a stale proposal must never fire reminders or auto-approve."""
    proposal_path = tmp_path / "proposal.json"
    today_path = tmp_path / "today_plan.json"
    state_path = tmp_path / "state.json"
    write_json(proposal_path, _proposal("16:30", for_date="2026-10-06"))
    notify = lambda title, message: None  # noqa: E731

    actions = reminders.check_reminders(
        datetime.fromisoformat("2026-10-07T16:31"),
        notify,
        proposal_path=proposal_path,
        today_path=today_path,
        state_path=state_path,
    )
    assert actions == []
    assert not today_path.exists()


def test_read_todays_walk_only_returns_todays_approval(tmp_path):
    path = tmp_path / "today_plan.json"
    now = datetime.fromisoformat("2026-10-07T12:00")
    assert reminders.read_todays_walk(path, now) is None  # missing file
    write_json(path, _approved("2026-10-06").to_dict())
    assert reminders.read_todays_walk(path, now) is None  # yesterday's leftover
    write_json(path, _approved("2026-10-07").to_dict())
    record = reminders.read_todays_walk(path, now)
    assert record is not None
    assert record.approved_by == "auto"


def test_check_reminders_approves_past_yesterdays_leftover(tmp_path):
    """A leftover approval from yesterday must not block today's reminders."""
    proposal_path = tmp_path / "proposal.json"
    today_path = tmp_path / "today_plan.json"
    state_path = tmp_path / "state.json"
    write_json(proposal_path, _proposal("16:30"))
    write_json(today_path, _approved("2026-10-06").to_dict())
    notify = lambda title, message: None  # noqa: E731
    paths = {
        "proposal_path": proposal_path,
        "today_path": today_path,
        "state_path": state_path,
    }

    day = "2026-10-07"
    assert reminders.check_reminders(
        datetime.fromisoformat(f"{day}T16:00"), notify, **paths
    ) == ["reminder-30"]
    actions = reminders.check_reminders(
        datetime.fromisoformat(f"{day}T16:31"), notify, **paths
    )
    assert "auto-approved" in actions
    today = read_json(today_path)
    assert today["for_date"] == "2026-10-07"  # replaced with today's approval
    assert today["approved_by"] == "auto"


def test_check_reminders_silent_when_todays_approval_exists(tmp_path):
    """Today's own approval still means: nothing left to remind or approve."""
    proposal_path = tmp_path / "proposal.json"
    today_path = tmp_path / "today_plan.json"
    state_path = tmp_path / "state.json"
    write_json(proposal_path, _proposal("16:30"))
    write_json(today_path, _approved("2026-10-07").to_dict())
    notify = lambda title, message: None  # noqa: E731

    actions = reminders.check_reminders(
        datetime.fromisoformat("2026-10-07T16:31"),
        notify,
        proposal_path=proposal_path,
        today_path=today_path,
        state_path=state_path,
    )
    assert actions == []
    assert read_json(today_path)["for_date"] == "2026-10-07"  # untouched


def test_run_daemon_keeps_running_despite_yesterdays_file(tmp_path, monkeypatch):
    """A leftover file must not make the daemon quit before today's walk."""
    stale = tmp_path / "today_plan.json"
    write_json(stale, _approved("2026-10-06").to_dict())
    checks: list[int] = []
    slept: list[int] = []

    def boom(_seconds):
        slept.append(1)
        raise KeyboardInterrupt

    monkeypatch.setattr(config, "TODAY_PLAN_PATH", stale)
    monkeypatch.setattr(config, "load_settings", lambda: object())
    monkeypatch.setattr(config, "load_user_plan", lambda: UserPlan())
    monkeypatch.setattr(reminders, "refresh_from_settings", lambda settings: None)
    monkeypatch.setattr(reminders, "ensure_proposal", lambda base, weather: None)
    monkeypatch.setattr(
        reminders, "check_reminders", lambda: checks.append(1) or []
    )
    monkeypatch.setattr(reminders, "time", SimpleNamespace(sleep=boom))

    reminders.run_daemon()
    assert checks, "daemon never reached its loop"
    assert slept, "daemon quit on yesterday's file instead of waiting"


def test_write_today_plan_records_edit(tmp_path):
    today_path = tmp_path / "today_plan.json"
    record = reminders.write_today_plan(
        Proposal.from_dict(_proposal()),
        "17:15",
        45,
        approved_by="edit",
        now=datetime.fromisoformat("2026-10-07T15:00"),
        today_path=today_path,
    )
    assert record.suggested_time == "17:15"
    assert record.duration_minutes == 45
    assert record.approved_by == "edit"
    assert read_json(today_path)["duration_minutes"] == 45


def _approved_with_fp(base_plan, when="16:30", for_date="2026-10-07"):
    data = _proposal(when, for_date=for_date)
    data["base_fingerprint"] = base_plan.fingerprint()
    return Proposal.from_dict(data).approve(
        f"{for_date}T15:00", approved_by="auto"
    )


def test_refresh_stale_approval_replaces_when_schedule_changed(tmp_path):
    """An approval built from an old schedule is rebuilt from the proposal."""
    from dataclasses import replace

    today_path = tmp_path / "today_plan.json"
    old = UserPlan(preferred_time="16:30", duration_minutes=30)
    new = UserPlan(preferred_time="09:00", duration_minutes=45)
    write_json(today_path, _approved_with_fp(old).to_dict())

    proposal = replace(
        Proposal.from_dict(_proposal("09:00")),
        base_fingerprint=new.fingerprint(),
        duration_minutes=45,
    )
    now = datetime.fromisoformat("2026-10-07T10:00")
    updated = reminders.refresh_stale_approval(
        new, proposal, now=now, today_path=today_path
    )
    assert updated is not None
    assert updated.suggested_time == "09:00"
    assert updated.duration_minutes == 45
    assert updated.base_fingerprint == new.fingerprint()
    assert read_json(today_path)["suggested_time"] == "09:00"


def test_refresh_stale_approval_leaves_matching_schedule(tmp_path):
    """Same schedule -> the approval (even an edit) is left untouched."""
    today_path = tmp_path / "today_plan.json"
    base = UserPlan(preferred_time="16:30", duration_minutes=30)
    # an edited approval: 17:15/45, but from the same standing schedule
    reminders.write_today_plan(
        Proposal.from_dict(
            {**_proposal(), "base_fingerprint": base.fingerprint()}
        ),
        "17:15",
        45,
        approved_by="edit",
        now=datetime.fromisoformat("2026-10-07T15:00"),
        today_path=today_path,
    )
    now = datetime.fromisoformat("2026-10-07T16:00")
    proposal = Proposal.from_dict(_proposal("16:30"))
    result = reminders.refresh_stale_approval(
        base, proposal, now=now, today_path=today_path
    )
    assert result is None  # no change
    assert read_json(today_path)["suggested_time"] == "17:15"  # edit kept
    assert read_json(today_path)["duration_minutes"] == 45


def test_refresh_stale_approval_noop_without_approval(tmp_path):
    today_path = tmp_path / "today_plan.json"
    base = UserPlan(preferred_time="16:30", duration_minutes=30)
    proposal = Proposal.from_dict(_proposal("16:30"))
    result = reminders.refresh_stale_approval(
        base, proposal,
        now=datetime.fromisoformat("2026-10-07T10:00"),
        today_path=today_path,
    )
    assert result is None
    assert not today_path.exists()  # nothing created before approval is due


def test_ensure_proposal_reuses_regenerates_and_forces(tmp_path):
    proposal_path = tmp_path / "proposal.json"
    calls = []

    def llm_fn(prompt):
        calls.append(prompt)
        return {"suggested_time": "17:00", "duration_minutes": 40,
                "reason": "because rain"}

    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    now = datetime.fromisoformat("2026-10-07T09:00")

    first = proposals.ensure_proposal(plan, None, now=now,
                                      proposal_path=proposal_path, llm_fn=llm_fn)
    assert first.suggested_time == "17:00"
    reused = proposals.ensure_proposal(plan, None, now=now,
                                       proposal_path=proposal_path, llm_fn=llm_fn)
    assert reused.created_at == first.created_at
    assert len(calls) == 1

    # weather changed -> fingerprint mismatch -> regenerate
    rain = Weather(summary="slight rain", temperature_2m=25.0,
                   precipitation_probability_max=70)
    proposals.ensure_proposal(plan, rain, now=now,
                              proposal_path=proposal_path, llm_fn=llm_fn)
    assert len(calls) == 2

    proposals.ensure_proposal(plan, rain, now=now, force=True,
                              proposal_path=proposal_path, llm_fn=llm_fn)
    assert len(calls) == 3


def test_ensure_proposal_no_churn_after_walk_time(tmp_path):
    """B2: a proposal already past its walk time is still valid for today."""
    proposal_path = tmp_path / "proposal.json"
    calls = []

    def llm_fn(prompt):
        calls.append(prompt)
        return {"suggested_time": "16:30", "duration_minutes": 30, "reason": "x"}

    plan = UserPlan(preferred_time="16:30")
    proposals.ensure_proposal(plan, None,
                              now=datetime.fromisoformat("2026-10-07T09:00"),
                              proposal_path=proposal_path, llm_fn=llm_fn)
    # later the same day, past approve_by (16:30): must reuse, not regenerate
    proposals.ensure_proposal(plan, None,
                              now=datetime.fromisoformat("2026-10-07T17:00"),
                              proposal_path=proposal_path, llm_fn=llm_fn)
    assert len(calls) == 1


def test_ensure_proposal_regenerates_on_new_day(tmp_path):
    proposal_path = tmp_path / "proposal.json"
    calls = []

    def llm_fn(prompt):
        calls.append(prompt)
        return {"suggested_time": "16:30", "duration_minutes": 30, "reason": "x"}

    plan = UserPlan(preferred_time="16:30")
    proposals.ensure_proposal(plan, None,
                              now=datetime.fromisoformat("2026-10-07T09:00"),
                              proposal_path=proposal_path, llm_fn=llm_fn)
    proposals.ensure_proposal(plan, None,
                              now=datetime.fromisoformat("2026-10-08T09:00"),
                              proposal_path=proposal_path, llm_fn=llm_fn)
    assert len(calls) == 2


def test_ensure_proposal_regenerates_when_schedule_changes(tmp_path):
    """A wizard change to the schedule must regenerate, same day, no --force."""
    proposal_path = tmp_path / "proposal.json"
    calls = []

    def llm_fn(prompt):
        calls.append(prompt)
        return {"suggested_time": "16:30", "duration_minutes": 30, "reason": "x"}

    now = datetime.fromisoformat("2026-10-07T09:00")
    old = UserPlan(preferred_time="16:30", duration_minutes=30)
    proposals.ensure_proposal(old, None, now=now,
                              proposal_path=proposal_path, llm_fn=llm_fn)
    assert len(calls) == 1

    # same day, same weather, new schedule -> must not reuse
    new = UserPlan(preferred_time="22:30", duration_minutes=240)
    proposals.ensure_proposal(new, None, now=now,
                              proposal_path=proposal_path, llm_fn=llm_fn)
    assert len(calls) == 2


def test_ensure_proposal_ignores_unusable_llm_reply(tmp_path):
    """The reply validator runs on the production path, not only in tests."""
    proposal_path = tmp_path / "proposal.json"
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    reply = {"suggested_time": "25:00", "duration_minutes": 45, "reason": "bad"}

    proposal = proposals.ensure_proposal(
        plan,
        None,
        now=datetime.fromisoformat("2026-10-07T09:00"),
        proposal_path=proposal_path,
        llm_fn=lambda prompt: reply,
    )
    assert proposal.suggested_time == "16:30"  # fell back, no crash
    assert proposal.duration_minutes == 30
    assert "base plan" in proposal.reason


def test_ensure_proposal_rejects_drift_outside_window(tmp_path):
    """A model that ignores the shift limit gets dropped, not obeyed."""
    proposal_path = tmp_path / "proposal.json"
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    drift = {"suggested_time": "18:30", "duration_minutes": 30,
             "reason": "felt like evening"}

    proposal = proposals.ensure_proposal(
        plan,
        None,
        now=datetime.fromisoformat("2026-10-07T09:00"),
        proposal_path=proposal_path,
        llm_fn=lambda prompt: drift,
    )
    assert proposal.suggested_time == "16:30"
    assert "base plan" in proposal.reason


def test_ensure_proposal_echoes_out_of_window_user_choice(tmp_path):
    """A model that correctly echoes 22:30 / 240 keeps its reason."""
    proposal_path = tmp_path / "proposal.json"
    plan = UserPlan(preferred_time="22:30", duration_minutes=240)
    echo = {"suggested_time": "22:30", "duration_minutes": 240,
            "reason": "late walk, keep it"}

    proposal = proposals.ensure_proposal(
        plan,
        None,
        now=datetime.fromisoformat("2026-10-08T10:00"),
        proposal_path=proposal_path,
        llm_fn=lambda prompt: echo,
    )
    assert proposal.suggested_time == "22:30"
    assert proposal.duration_minutes == 240
    assert proposal.reason == "late walk, keep it"
