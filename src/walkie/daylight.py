"""Daylight window for the walking location (astral, pure computation).

No network: sunrise/sunset/day length come from the solar equations for
the configured coordinates, so this works fully offline.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun as astral_sun

from walkie import clock
from walkie.models import Daylight


def daylight_for(
    lat: float,
    lon: float,
    timezone_name: str,
    on: date | None = None,
) -> Daylight:
    """Sunrise/sunset/day length for one local date.

    Polar edge cases or bad coordinates degrade to sunrise/sunset=None
    instead of raising — daylight is an input, never a hard failure.
    """
    on = on or clock.now().date()
    try:
        info = LocationInfo("walkie", "", timezone_name, lat, lon)
        moments = astral_sun(
            info.observer, date=on, tzinfo=ZoneInfo(timezone_name)
        )
    except (ValueError, KeyError, OSError, TypeError):
        return Daylight(for_date=on.isoformat())
    sunrise = moments["sunrise"]
    sunset = moments["sunset"]
    return Daylight(
        for_date=on.isoformat(),
        sunrise=sunrise.strftime("%H:%M"),
        sunset=sunset.strftime("%H:%M"),
        daylight_minutes=int((sunset - sunrise).total_seconds() // 60),
    )
