import pytest

from walkie.models import (
    Daylight,
    Intensity,
    LocationType,
    Plan,
    Proposal,
    TodayPlan,
    UserPlan,
    Weather,
)


def test_user_plan_roundtrip():
    plan = UserPlan(
        preferred_time="16:30",
        duration_minutes=45,
        location_type=LocationType.SUN,
        intensity=Intensity.BRISK,
        area="Riverside",
        quote="Walk.",
        created_at="2026-10-07T12:00:00",
    )
    assert UserPlan.from_dict(plan.to_dict()) == plan


def test_user_plan_from_dict_tolerates_bad_values():
    plan = UserPlan.from_dict(
        {
            "preferred_time": "16:30",
            "duration_minutes": "soon",
            "location_type": "beach",
            "intensity": "extreme",
            "unknown_key": 1,
        }
    )
    assert plan.preferred_time == "16:30"
    assert plan.duration_minutes == 30  # falls back to default
    assert plan.location_type is LocationType.SHADE
    assert plan.intensity is Intensity.MODERATE
    assert plan.to_dict().keys() == UserPlan().to_dict().keys()


def test_user_plan_from_legacy_file_without_enums_as_plain_strings():
    # files written before enums: plain strings must still parse
    plan = UserPlan.from_dict(
        {"location_type": "shade", "intensity": "relaxed", "area": ""}
    )
    assert plan.location_type is LocationType.SHADE
    assert plan.intensity is Intensity.RELAXED


def test_proposal_roundtrip():
    proposal = Proposal(
        suggested_time="17:00",
        duration_minutes=40,
        location_type=LocationType.ANY,
        intensity=Intensity.RELAXED,
        reason="rain at noon",
        for_date="2026-10-07",
        approve_by="2026-10-07T17:00",
    )
    assert Proposal.from_dict(proposal.to_dict()) == proposal
    data = proposal.to_dict()
    assert data["location_type"] == "any"
    assert data["intensity"] == "relaxed"


def test_proposal_from_dict_defaults_when_fields_missing():
    proposal = Proposal.from_dict({})
    assert proposal.weather_fingerprint == "unavailable"
    assert proposal.duration_minutes == 30
    assert proposal.for_date == ""


def test_today_plan_keeps_proposal_and_approval_fields():
    record = TodayPlan.from_dict(
        {
            "suggested_time": "16:30",
            "duration_minutes": 30,
            "approved_at": "2026-10-07T16:05:00",
            "approved_by": "auto",
        }
    )
    assert isinstance(record, TodayPlan)
    assert record.suggested_time == "16:30"
    assert record.approved_by == "auto"
    data = record.to_dict()
    assert data["approved_by"] == "auto"
    assert "for_date" in data


def test_approve_works_on_a_today_plan_instance():
    """Re-approving an already-approved record must not pass its own fields twice."""
    record = TodayPlan.from_dict(
        {
            "suggested_time": "16:30",
            "approved_at": "2026-10-07T16:05:00",
            "approved_by": "auto",
        }
    )
    again = record.approve("2026-10-07T16:31:00", approved_by="edit")
    assert again.approved_by == "edit"
    assert again.suggested_time == "16:30"


def test_weather_from_partial_dict():
    weather = Weather.from_dict({"summary": "overcast", "temperature_2m": 27.8})
    assert weather.summary == "overcast"
    assert weather.temperature_2m == pytest.approx(27.8)
    assert weather.temperature_2m_max is None
    assert weather.fetched_at == 0


def test_plan_roundtrip_and_clean_json():
    import json

    plan = Plan(
        for_date="2026-10-07",
        window_start="17:00",
        window_end="17:45",
        duration_minutes=45,
        location_type=LocationType.SUN,
        intensity=Intensity.BRISK,
        area="Riverside",
        sunrise="06:14",
        sunset="18:15",
        daylight_minutes=721,
        weather_summary="overcast",
        reason="rain at noon",
        route_notes="ridge loop",
        source="llm",
        created_at="2026-10-07T09:00:00",
    )
    assert Plan.from_dict(plan.to_dict()) == plan
    assert Plan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan


def test_plan_from_dict_defaults_on_missing_or_bad_values():
    plan = Plan.from_dict(
        {"duration_minutes": "soon", "location_type": "beach", "source": "x"}
    )
    assert plan.duration_minutes == 30
    assert plan.location_type is LocationType.SHADE
    assert plan.weather_fingerprint == "unavailable"
    assert plan.sunrise is None


def test_daylight_roundtrip_and_partial():
    day = Daylight(for_date="2026-10-07", sunrise="06:14", sunset="18:15",
                   daylight_minutes=721)
    assert Daylight.from_dict(day.to_dict()) == day
    empty = Daylight.from_dict({})
    assert empty.sunrise is None and empty.daylight_minutes == 0
