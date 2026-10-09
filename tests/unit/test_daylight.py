from datetime import date

from walkie.daylight import daylight_advisory, daylight_for
from walkie.models import Daylight

LAGOS = (6.31625, 8.11691, "Africa/Lagos")

# ~12h day near the equator, used by the advisory tests below
DAY = Daylight(for_date="2026-10-07", sunrise="06:15", sunset="18:20",
               daylight_minutes=725)


def test_daylight_for_lagos_october():
    day = daylight_for(*LAGOS, on=date(2026, 10, 7))
    assert day.for_date == "2026-10-07"
    assert day.sunrise is not None and day.sunrise.startswith("06:")
    assert day.sunset is not None and day.sunset.startswith("18:")
    assert 660 <= day.daylight_minutes <= 780  # ~12 h near the equator


def test_daylight_polar_winter_degrades_to_none():
    day = daylight_for(89.0, 0.0, "UTC", on=date(2026, 12, 21))
    assert day.sunrise is None
    assert day.sunset is None
    assert day.daylight_minutes == 0


def test_daylight_bad_timezone_degrades_to_none():
    day = daylight_for(6.3, 8.1, "Not/AZone", on=date(2026, 10, 7))
    assert day.sunrise is None


def test_daylight_roundtrip():
    day = daylight_for(*LAGOS, on=date(2026, 10, 7))
    assert Daylight.from_dict(day.to_dict()) == day


def test_advisory_empty_when_walk_fits_daylight():
    assert daylight_advisory("10:00", "10:30", DAY) == ""
    # touching the boundaries exactly still counts as fitting
    assert daylight_advisory("06:15", "18:20", DAY) == ""


def test_advisory_flags_before_sunrise_and_after_sunset():
    assert daylight_advisory("05:30", "06:00", DAY) == (
        "starts before sunrise (06:15)"
    )
    assert daylight_advisory("18:30", "19:15", DAY) == (
        "ends after sunset (18:20)"
    )


def test_advisory_flags_both_ends_and_straddles():
    assert daylight_advisory("05:00", "19:00", DAY) == (
        "starts before sunrise (06:15); ends after sunset (18:20)"
    )
    # a window that crosses midnight counts as ending after sunset
    assert daylight_advisory("23:00", "00:30", DAY) == (
        "ends after sunset (18:20)"
    )
    # starting before sunrise and running past midnight: both notes
    assert daylight_advisory("05:30", "00:10", DAY) == (
        "starts before sunrise (06:15); ends after sunset (18:20)"
    )


def test_advisory_silent_when_daylight_unknown_or_bad():
    polar = Daylight(for_date="2026-12-21")  # sunrise/sunset None
    assert daylight_advisory("05:30", "06:00", polar) == ""
    bad = Daylight(for_date="2026-10-07", sunrise="06:15", sunset="18:20")
    assert daylight_advisory("25:00", "26:00", bad) == ""  # unparseable window
