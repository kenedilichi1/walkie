from walkie.ai.prompt import SYSTEM_PROMPT, build_user_prompt
from walkie.models import Daylight, Proposal, UserPlan, Weather
from walkie.suggest.prompts import build_prompt


def test_system_prompt_demands_strict_json_with_schema():
    assert "ONLY a JSON object" in SYSTEM_PROMPT
    for key in (
        "window_start",
        "duration_minutes",
        "location_type",
        "intensity",
        "reason",
        "route_notes",
    ):
        assert key in SYSTEM_PROMPT
    # the concrete window is per-plan (user prompt), not a fixed global
    assert "the user message states the exact time window" in SYSTEM_PROMPT


def test_user_prompt_includes_structured_inputs():
    plan = UserPlan(preferred_time="16:30", duration_minutes=30, area="Riverside")
    weather = Weather(
        summary="overcast",
        temperature_2m=27.8,
        temperature_2m_max=30.0,
        precipitation_probability_max=40,
        wind_speed_10m=9.0,
    )
    daylight = Daylight(
        for_date="2026-10-07",
        sunrise="06:14",
        sunset="18:15",
        daylight_minutes=721,
    )
    text = build_user_prompt(plan, weather, daylight)
    assert "16:30" in text and "30 min" in text and "Riverside" in text
    assert "overcast" in text and "rain chance 40%" in text
    assert "sunrise 06:14" in text and "721 min of daylight" in text


def test_user_prompt_states_the_allowed_window():
    """The prompt tells the model exactly the window the validator enforces."""
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    text = build_user_prompt(plan, None, None)
    assert "between 15:30 and 17:30" in text
    assert "between 15 and 45" in text


def test_user_prompt_says_keep_exactly_outside_window():
    """A 22:30 / 240 min choice is untouchable, and the prompt says so."""
    plan = UserPlan(preferred_time="22:30", duration_minutes=240)
    text = build_user_prompt(plan, None, None)
    assert "keep the start at exactly 22:30" in text
    assert "keep duration_minutes at exactly 240" in text


def test_proposal_prompt_states_the_allowed_window():
    plan = UserPlan(preferred_time="16:30", duration_minutes=30)
    text = build_prompt(plan, None)
    assert "between 15:30 and 17:30" in text
    assert "between 15 and 45" in text


def test_proposal_prompt_says_keep_exactly_outside_window():
    plan = UserPlan(preferred_time="22:30", duration_minutes=240)
    text = build_prompt(plan, None)
    assert "keep the start at exactly 22:30" in text
    assert "keep duration_minutes at exactly 240" in text


def test_user_prompt_prefers_proposal_window():
    proposal = Proposal(
        suggested_time="17:00", duration_minutes=45, reason="rain at noon"
    )
    text = build_user_prompt(UserPlan(), None, None, proposal)
    assert "17:00" in text and "45 min" in text and "rain at noon" in text


def test_user_prompt_degrades_offline():
    text = build_user_prompt(UserPlan(), None, None)
    assert "weather unavailable" in text
    assert "daylight unknown" in text
