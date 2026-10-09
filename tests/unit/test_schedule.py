import pytest

from walkie import config, schedule
from walkie.models import Intensity, LocationType, UserPlan


def _plan(**overrides) -> UserPlan:
    base = {
        "preferred_time": "16:30",
        "duration_minutes": 30,
        "location_type": LocationType.SHADE,
        "intensity": Intensity.MODERATE,
        "area": "Riverside",
    }
    base.update(overrides)
    return UserPlan(**base)


def test_load_current_defaults_when_file_missing(tmp_path):
    plan = schedule.load_current(tmp_path / "nope.json")
    assert plan == UserPlan()


def test_load_current_reads_saved_plan(tmp_path):
    path = tmp_path / "user_plan.json"
    config.save_user_plan(_plan(), path)
    assert schedule.load_current(path).preferred_time == "16:30"


def test_validate_accepts_good_plan():
    schedule.validate(_plan())  # no raise


def test_validate_rejects_bad_time():
    with pytest.raises(schedule.ScheduleError, match="HH:MM"):
        schedule.validate(_plan(preferred_time="banana"))


def test_validate_rejects_duration_out_of_range():
    with pytest.raises(schedule.ScheduleError, match="duration"):
        schedule.validate(_plan(duration_minutes=1))


def test_apply_overrides_replaces_named_fields_only():
    updated = schedule.apply_overrides(_plan(), time="07:00", intensity="brisk")
    assert updated.preferred_time == "07:00"
    assert updated.intensity == Intensity.BRISK
    # untouched fields carry over
    assert updated.duration_minutes == 30
    assert updated.area == "Riverside"


def test_apply_overrides_none_means_keep():
    updated = schedule.apply_overrides(_plan(), time=None, duration=None)
    assert updated == _plan()


def test_apply_overrides_parses_location_and_intensity():
    updated = schedule.apply_overrides(_plan(), location="sun", intensity="relaxed")
    assert updated.location_type == LocationType.SUN
    assert updated.intensity == Intensity.RELAXED


def test_apply_overrides_rejects_unknown_location():
    with pytest.raises(schedule.ScheduleError, match="location"):
        schedule.apply_overrides(_plan(), location="beach")


def test_apply_overrides_rejects_unknown_intensity():
    with pytest.raises(schedule.ScheduleError, match="intensity"):
        schedule.apply_overrides(_plan(), intensity="hardcore")


def test_save_writes_and_stamps(tmp_path):
    path = tmp_path / "user_plan.json"
    saved = schedule.save(_plan(), path)
    assert path.exists()
    assert saved.created_at  # stamped on save
    assert schedule.load_current(path).preferred_time == "16:30"


def test_save_rejects_bad_time_before_writing(tmp_path):
    path = tmp_path / "user_plan.json"
    with pytest.raises(schedule.ScheduleError):
        schedule.save(_plan(preferred_time="nope"), path)
    assert not path.exists()


def test_describe_includes_key_fields():
    text = schedule.describe(_plan())
    assert "16:30" in text
    assert "30 min" in text
    assert "Riverside" in text


def test_describe_omits_empty_area():
    text = schedule.describe(_plan(area=""))
    assert "Riverside" not in text
