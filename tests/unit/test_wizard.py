from walkie import config, region
from walkie.models import Intensity, LocationType, UserPlan
from walkie.ui.app import ensure_app
from walkie.ui.widgets import make_duration_spin
from walkie.ui.wizard import (
    PlanWizard,
    StartPointPage,
    detect_guess,
    load_saved_plan,
    save_plan,
    save_start_point,
    saved_point,
)

ensure_app()  # process-wide offscreen app (platform set in tests/conftest.py)


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


def test_duration_spin_accepts_long_user_walks():
    """User scope: the wizard must not cap walks at the model's 180 min."""
    spin = make_duration_spin(240)
    assert spin.value() == 240
    spin.setValue(480)
    assert spin.value() == 480


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


def test_start_page_is_first_and_defaults_to_guess():
    wizard = PlanWizard(guess=(6.31625, 8.11691))
    page = wizard.page(0)
    assert isinstance(page, StartPointPage)
    assert page.use_guess_btn.isChecked()
    assert page.validatePage() is True
    assert wizard.start_point() == (6.31625, 8.11691)


def test_start_page_without_guess_defaults_to_paste():
    wizard = PlanWizard(guess=None)
    page = wizard.start_page
    assert page.paste_btn.isChecked()
    assert not page.use_guess_btn.isEnabled()
    assert "couldn't guess" in page.guess_label.text().lower()


def test_start_page_paste_link_sets_exact_point():
    wizard = PlanWizard(guess=None)
    page = wizard.start_page
    page.paste_edit.setText("https://www.google.com/maps?q=6.31625,8.11691")
    assert page.validatePage() is True
    assert wizard.start_point() == (6.31625, 8.11691)
    assert "6.31625" in page.status_label.text()


def test_start_page_rejects_link_without_coordinates(monkeypatch):
    monkeypatch.setattr(region, "resolve_link", lambda url: None)
    wizard = PlanWizard(guess=None)
    page = wizard.start_page
    page.paste_edit.setText("https://maps.app.goo.gl/AbCdEfGh")
    assert page.validatePage() is False
    assert wizard.start_point() is None
    assert "No coordinates" in page.status_label.text()


def test_start_page_guess_mode_blocked_without_guess():
    wizard = PlanWizard(guess=None)
    page = wizard.start_page
    page.use_guess_btn.setChecked(True)
    assert page.validatePage() is False
    assert "No guess" in page.status_label.text()


def test_start_page_address_geocodes(monkeypatch):
    monkeypatch.setattr(
        region, "geocode_place",
        lambda q: (6.31625, 8.11691, "Riverside, Calabar"),
    )
    wizard = PlanWizard(guess=None)
    page = wizard.start_page
    page.address_btn.setChecked(True)
    page.address_edit.setText("Riverside")
    assert page.validatePage() is True
    assert wizard.start_point() == (6.31625, 8.11691)


def test_start_page_address_failure_keeps_user_on_page(monkeypatch):
    monkeypatch.setattr(region, "geocode_place", lambda q: None)
    wizard = PlanWizard(guess=None)
    page = wizard.start_page
    page.address_btn.setChecked(True)
    page.address_edit.setText("Nowhereville")
    assert page.validatePage() is False
    assert wizard.start_point() is None
    assert "Couldn't find" in page.status_label.text()


def _settings_template(tz="UTC"):
    return (
        "region:\n"
        "  name: Nigeria\n"
        "  pbf: data/osm/nigeria-latest.osm.pbf\n"
        "location:\n"
        "  lat: 6.0\n"
        "  lon: 8.0\n"
        f"  timezone: {tz}\n"
    )


def test_save_start_point_takes_timezone_only_from_detection(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(_settings_template())
    detected = (6.31625, 8.11691, "Nigeria", "ng", "Africa/Lagos")

    save_start_point((6.31625, 8.11691), detected, settings_path=settings)
    text = settings.read_text()
    assert "lat: 6.31625" in text
    assert "timezone: Africa/Lagos" in text

    settings.write_text(_settings_template())
    save_start_point((1.5, 2.5), detected, settings_path=settings)
    text = settings.read_text()
    assert "lat: 1.5" in text
    assert "lon: 2.5" in text
    assert "timezone: UTC" in text  # pasted point must not drag the tz


def test_save_start_point_without_detection_leaves_tz(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(_settings_template())
    save_start_point((6.31625, 8.11691), None, settings_path=settings)
    text = settings.read_text()
    assert "lat: 6.31625" in text
    assert "timezone: UTC" in text


def test_detect_guess_returns_none_when_offline(monkeypatch):
    def boom():
        raise region.RegionError("offline")

    monkeypatch.setattr(region, "detect_location", boom)
    assert detect_guess() is None


def test_detect_guess_passes_detection_through(monkeypatch):
    found = (6.31625, 8.11691, "Nigeria", "ng", "Africa/Lagos")
    monkeypatch.setattr(region, "detect_location", lambda: found)
    assert detect_guess() == found


def test_saved_point_reads_settings(monkeypatch):
    class _Settings:
        lat, lon = 6.31625, 8.11691

    monkeypatch.setattr(config, "load_settings", lambda: _Settings())
    assert saved_point() == (6.31625, 8.11691)


def test_saved_point_none_when_settings_unreadable(monkeypatch):
    def boom(path=None):
        raise config.ConfigError("missing")

    monkeypatch.setattr(config, "load_settings", boom)
    assert saved_point() is None


def test_start_page_paste_tolerates_invisible_noise():
    wizard = PlanWizard(guess=None)
    page = wizard.start_page
    page.paste_edit.setText("\u200b5.35251, 7.08292\u200b")
    assert page.validatePage() is True
    assert wizard.start_point() == (5.35251, 7.08292)
    assert "5.35251" in page.status_label.text()
