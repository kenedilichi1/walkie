from datetime import date

from walkie.daylight import daylight_for
from walkie.models import Daylight

LAGOS = (6.31625, 8.11691, "Africa/Lagos")


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
