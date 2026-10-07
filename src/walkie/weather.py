"""Open-Meteo forecast fetch with a local, staleness-aware cache.

Offline-first: when a fetch fails but a cache exists, the stale cache wins.
Also home of the weather summary/fingerprint used in prompts and validity.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import requests

from walkie import clock
from walkie.config import DEFAULT_FORECAST_URL, Settings
from walkie.log import get_logger
from walkie.models import FINGERPRINT_UNAVAILABLE, Weather
from walkie.storage import read_record, write_json

log = get_logger("weather")

FORECAST_TIMEOUT_S = 15
DEFAULT_MAX_AGE_HOURS = 2.0
# fingerprint buckets: rain probability (<= limit) -> label
RAIN_BUCKETS = ((10, "low"), (30, "mild"), (60, "med"))

WMO_SUMMARY = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight showers",
    81: "moderate showers",
    82: "violent showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def describe_weather_code(code: int) -> str:
    return WMO_SUMMARY.get(code, "unknown conditions")


def fetch_forecast(
    lat: float,
    lon: float,
    timezone_name: str,
    url: str = DEFAULT_FORECAST_URL,
) -> Weather | None:
    """Fetch today's forecast; returns compact Weather, or None on failure."""
    try:
        params: dict[str, str | float] = {
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,precipitation,weather_code,"
                "wind_speed_10m,cloud_cover"
            ),
            "hourly": "temperature_2m,precipitation_probability",
            "timezone": timezone_name,
            "forecast_days": 1,
        }
        response = requests.get(
            url,
            params=params,
            timeout=FORECAST_TIMEOUT_S,
        )
        response.raise_for_status()
        return compact_forecast(response.json(), timezone_name)
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        log.warning(f"forecast fetch failed ({exc}) — falling back to cache")
        return None


def compact_forecast(raw: dict[str, Any], timezone_name: str) -> Weather:
    """Reduce an Open-Meteo response to the fields walkie cares about.

    Missing or null samples are dropped field by field: an empty hourly
    list yields None min/max instead of failing the whole forecast.
    """
    current = raw.get("current") or {}
    hourly = raw.get("hourly") or {}
    temps = [t for t in hourly.get("temperature_2m") or [] if t is not None]
    if not temps:
        temps = [t for t in [current.get("temperature_2m")] if t is not None]
    rain_probs = [
        p for p in hourly.get("precipitation_probability") or [] if p is not None
    ]
    weather = Weather.from_dict(
        {
            "fetched_at": int(clock.now().timestamp()),
            "timezone": timezone_name,
            "weather_code": current.get("weather_code", -1),
            "temperature_2m": current.get("temperature_2m"),
            "temperature_2m_min": min(temps, default=None),
            "temperature_2m_max": max(temps, default=None),
            "precipitation_mm": current.get("precipitation", 0.0),
            "precipitation_probability_max": max(rain_probs, default=0),
            "wind_speed_10m": current.get("wind_speed_10m"),
            "cloud_cover": current.get("cloud_cover"),
        }
    )
    return replace(weather, summary=describe_weather_code(weather.weather_code))


def load_cache(cache_path: Path) -> Weather | None:
    return read_record(cache_path, Weather.from_dict)


def is_stale(cache: Weather | None, max_age_hours: float = DEFAULT_MAX_AGE_HOURS) -> bool:
    if cache is None:
        return True
    return (clock.now().timestamp() - cache.fetched_at) > max_age_hours * 3600


def save_cache(cache_path: Path, weather: Weather) -> None:
    write_json(cache_path, weather.to_dict())


def refresh_if_stale(
    cache_path: Path,
    lat: float,
    lon: float,
    timezone_name: str,
    url: str = DEFAULT_FORECAST_URL,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    force: bool = False,
) -> Weather | None:
    """Return fresh weather, refetching only when the cache is stale/missing."""
    cached = load_cache(cache_path)
    if cached is not None and not force and not is_stale(cached, max_age_hours):
        return cached
    fresh = fetch_forecast(lat, lon, timezone_name, url)
    if fresh is None:
        return cached  # stale beats nothing (offline-first)
    save_cache(cache_path, fresh)
    return fresh


def refresh_from_settings(
    settings: Settings,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    force: bool = False,
) -> Weather | None:
    """refresh_if_stale wired from validated settings."""
    return refresh_if_stale(
        settings.weather_cache,
        settings.lat,
        settings.lon,
        settings.timezone,
        url=settings.forecast_url,
        max_age_hours=max_age_hours,
        force=force,
    )


def weather_fingerprint(weather: Weather | None) -> str:
    """Bucketed fingerprint: stable across jitter, flips when conditions change."""
    if weather is None:
        return FINGERPRINT_UNAVAILABLE
    temp = weather.temperature_2m
    temp_bucket = "?" if temp is None else f"{round(temp / 5) * 5:.0f}C"
    rain = weather.precipitation_probability_max
    rain_bucket = next(
        (label for limit, label in RAIN_BUCKETS if rain <= limit),
        "high",
    )
    return f"{weather.summary}|{temp_bucket}|{rain_bucket}"


def weather_line(weather: Weather | None) -> str:
    if weather is None:
        return "weather unavailable (offline)"
    high = (
        weather.temperature_2m_max
        if weather.temperature_2m_max is not None
        else weather.temperature_2m
    )
    wind = weather.wind_speed_10m
    return (
        f"{weather.summary or 'unknown'}, {_deg(weather.temperature_2m)} "
        f"(high {_deg(high)}), "
        f"rain chance {weather.precipitation_probability_max}%, "
        f"wind {wind if wind is not None else '?'} km/h"
    )


def _deg(value: float | None) -> str:
    """A temperature for prompt text; '?' instead of the literal 'None'."""
    return f"{value}C" if value is not None else "?C"
