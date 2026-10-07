import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from walkie.models import (  # noqa: E402
    Intensity,
    LocationType,
    UserPlan,
)
from walkie.ui.wizard import (  # noqa: E402
    PlanWizard,
    load_saved_plan,
    save_plan,
)

app = QApplication.instance() or QApplication([])


def test_wizard_roundtrips_full_plan():
    wizard = PlanWizard(
        UserPlan(
            preferred_time="16:30",
            duration_minutes=45,
            location_type=LocationType.SUN,
            intensity=Intensity.BRISK,
            area="Riverside",
        )
    )
    plan = wizard.plan()
    assert plan.preferred_time == "16:30"
    assert plan.duration_minutes == 45
    assert plan.location_type is LocationType.SUN
    assert plan.intensity is Intensity.BRISK
    assert plan.area == "Riverside"


def test_wizard_defaults_when_created_fresh():
    wizard = PlanWizard(UserPlan())
    plan = wizard.plan()
    assert plan.preferred_time == "12:30"
    assert plan.duration_minutes == 30
    assert plan.location_type is LocationType.SHADE


def test_save_and_load_plan(tmp_path):
    path = tmp_path / "user_plan.json"
    saved = save_plan(
        UserPlan(preferred_time="07:15", intensity=Intensity.RELAXED), path
    )
    assert saved.quote  # quote was filled in
    assert saved.created_at
    loaded = load_saved_plan(path)
    assert loaded.preferred_time == "07:15"
    assert loaded.intensity is Intensity.RELAXED


def test_load_saved_plan_missing_file_gives_defaults(tmp_path):
    loaded = load_saved_plan(tmp_path / "user_plan.json")
    assert loaded == UserPlan()
