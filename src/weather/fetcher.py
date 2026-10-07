"""Open-Meteo forecast fetch with a local, staleness-aware cache.

Writes/reads cache/weather_today.json (path from config/settings.yaml).
Offline-first: when a fetch fails but a cache exists, the stale cache wins.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

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
    url: str = "https://api.open-meteo.com/v1/forecast",
) -> dict | None:
    """Fetch today's forecast; returns a compact dict, or None on failure."""
    try:
        response = requests.get(
            url,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,precipitation,weather_code,"
                    "wind_speed_10m,cloud_cover"
                ),
                "hourly": "temperature_2m,precipitation_probability",
                "timezone": timezone_name,
                "forecast_days": 1,
            },
            timeout=15,
        )
        response.raise_for_status()
        return compact_forecast(response.json(), timezone_name)
    except (requests.RequestException, KeyError, ValueError):
        return None


def compact_forecast(raw: dict, timezone_name: str) -> dict:
    """Reduce an Open-Meteo response to the fields walkie cares about."""
    current = raw.get("current", {})
    hourly = raw.get("hourly", {})
    temps = hourly.get("temperature_2m") or [current.get("temperature_2m", 0.0)]
    rain_probs = hourly.get("precipitation_probability") or [0]
    weather_code = int(current.get("weather_code", -1))
    return {
        "fetched_at": int(time.time()),
        "timezone": timezone_name,
        "summary": describe_weather_code(weather_code),
        "weather_code": weather_code,
        "temperature_2m": current.get("temperature_2m"),
        "temperature_2m_min": min(t for t in temps if t is not None),
        "temperature_2m_max": max(t for t in temps if t is not None),
        "precipitation_mm": current.get("precipitation", 0.0),
        "precipitation_probability_max": max(
            (p for p in rain_probs if p is not None), default=0
        ),
        "wind_speed_10m": current.get("wind_speed_10m"),
        "cloud_cover": current.get("cloud_cover"),
    }


def load_cache(cache_path: Path) -> dict | None:
    try:
        return json.loads(Path(cache_path).read_text())
    except (OSError, ValueError):
        return None


def is_stale(cache: dict, max_age_hours: float = 2.0) -> bool:
    fetched_at = cache.get("fetched_at", 0)
    return (time.time() - fetched_at) > max_age_hours * 3600


def save_cache(cache_path: Path, data: dict) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def refresh_if_stale(
    cache_path: Path,
    lat: float,
    lon: float,
    timezone_name: str,
    url: str = "https://api.open-meteo.com/v1/forecast",
    max_age_hours: float = 2.0,
    force: bool = False,
) -> dict | None:
    """Return fresh weather, refetching only when the cache is stale/missing."""
    cached = load_cache(cache_path)
    if cached is not None and not force and not is_stale(cached, max_age_hours):
        return cached
    fresh = fetch_forecast(lat, lon, timezone_name, url)
    if fresh is None:
        return cached  # stale beats nothing (offline-first)
    save_cache(cache_path, fresh)
    return fresh
