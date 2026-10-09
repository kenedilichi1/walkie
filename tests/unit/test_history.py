from datetime import datetime

from walkie import history
from walkie.ai import planner
from walkie.models import Daylight, Plan, UserPlan

NOW = datetime.fromisoformat("2026-10-07T09:00")


def _plan(for_date: str) -> Plan:
    return Plan(for_date=for_date, window_start="13:00", window_end="13:30",
                duration_minutes=30)


def test_history_dir_sits_beside_plan_json(tmp_path):
    plan_path = tmp_path / "plans" / "plan.json"
    assert history.history_dir_for(plan_path) == tmp_path / "plans" / "history"


def test_archive_plan_writes_one_file_per_day(tmp_path):
    plan_path = tmp_path / "plan.json"
    dest = history.archive_plan(_plan("2026-10-07"), plan_path)
    assert dest == tmp_path / "history" / "plan-2026-10-07.json"
    assert dest.exists()
    # re-archiving the same day overwrites, not appends
    history.archive_plan(_plan("2026-10-07"), plan_path)
    assert list((tmp_path / "history").iterdir()) == [dest]


def test_archive_plan_skips_empty_date(tmp_path):
    plan_path = tmp_path / "plan.json"
    assert history.archive_plan(_plan(""), plan_path) is None
    assert not (tmp_path / "history").exists()


def test_load_history_newest_first_and_empty(tmp_path):
    plan_path = tmp_path / "plan.json"
    assert history.load_history(plan_path) == []  # empty before any archive

    history.archive_plan(_plan("2026-10-05"), plan_path)
    history.archive_plan(_plan("2026-10-07"), plan_path)
    history.archive_plan(_plan("2026-10-06"), plan_path)
    loaded = history.load_history(plan_path)
    assert [p.for_date for p in loaded] == ["2026-10-07", "2026-10-06",
                                            "2026-10-05"]
    assert history.load_history(plan_path, limit=2)[1].for_date == "2026-10-06"


def test_load_history_ignores_unreadable_file(tmp_path):
    plan_path = tmp_path / "plan.json"
    hdir = tmp_path / "history"
    hdir.mkdir()
    (hdir / "plan-2026-10-07.json").write_text("{ not json")
    history.archive_plan(_plan("2026-10-06"), plan_path)
    assert [p.for_date for p in history.load_history(plan_path)] == ["2026-10-06"]


def test_end_to_end_history_survives_a_fresh_plan(tmp_path):
    """The full flow: plan a day, roll to the next, and look back."""
    plan_path = tmp_path / "plan.json"
    base = UserPlan(preferred_time="13:00", duration_minutes=30)

    def llm(prompt):
        return {"window_start": "13:00", "duration_minutes": 30, "reason": "x"}

    daylight = Daylight(for_date="2026-10-07", sunrise="06:14", sunset="18:15",
                        daylight_minutes=721)
    planner.ensure_plan(base, None, daylight, now=NOW,
                        plan_path=plan_path, llm_fn=llm)
    planner.ensure_plan(base, None, daylight,
                        now=datetime.fromisoformat("2026-10-08T09:00"),
                        plan_path=plan_path, llm_fn=llm)

    past = history.load_history(plan_path)
    assert [p.for_date for p in past] == ["2026-10-07"]
