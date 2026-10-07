import time
from dataclasses import replace

import pytest

from walkie.models import Weather
from walkie.weather import (
    compact_forecast,
    describe_weather_code,
    is_stale,
    refresh_if_stale,
    save_cache,
    weather_fingerprint,
    weather_line,
)


def test_describe_weather_code_known_and_unknown():
    assert describe_weather_code(0) == "clear sky"
    assert describe_weather_code(61) == "slight rain"
    assert describe_weather_code(1234) == "unknown conditions"


def test_compact_forecast_reduces_payload():
    raw = {
        "current": {
            "temperature_2m": 27.8,
            "precipitation": 0.4,
            "weather_code": 3,
            "wind_speed_10m": 9.1,
            "cloud_cover": 88,
        },
        "hourly": {
            "temperature_2m": [24.0, 27.8, 31.2],
            "precipitation_probability": [10, 40, 95],
        },
    }
    result = compact_forecast(raw, "Africa/Lagos")
    assert result.summary == "overcast"
    assert result.temperature_2m_min == pytest.approx(24.0)
    assert result.temperature_2m_max == pytest.approx(31.2)
    assert result.precipitation_probability_max == 95
    assert result.timezone == "Africa/Lagos"


def test_is_stale_fresh_vs_old():
    assert not is_stale(Weather(fetched_at=int(time.time())), max_age_hours=2)
    assert is_stale(Weather(fetched_at=int(time.time()) - 7300), max_age_hours=2)
    assert is_stale(None)


def test_refresh_serves_fresh_cache_without_fetching(tmp_path, monkeypatch):
    cache = tmp_path / "weather.json"
    save_cache(cache, Weather(fetched_at=10**10, summary="cached"))

    def fail_fetch(*args, **kwargs):
        raise AssertionError("should not fetch when cache is fresh")

    monkeypatch.setattr("walkie.weather.fetch_forecast", fail_fetch)
    result = refresh_if_stale(cache, 6.3, 8.1, "Africa/Lagos")
    assert result is not None
    assert result.summary == "cached"


def test_refresh_refetches_when_stale(tmp_path, monkeypatch):
    cache = tmp_path / "weather.json"
    save_cache(cache, Weather(fetched_at=0, summary="old"))

    def fake_fetch(lat, lon, tz, url):
        return Weather(fetched_at=999, summary="fresh")

    monkeypatch.setattr("walkie.weather.fetch_forecast", fake_fetch)
    result = refresh_if_stale(cache, 6.3, 8.1, "Africa/Lagos")
    assert result is not None
    assert result.summary == "fresh"


def test_refresh_falls_back_to_stale_cache_when_offline(tmp_path, monkeypatch):
    cache = tmp_path / "weather.json"
    save_cache(cache, Weather(fetched_at=0, summary="stale-but-usable"))
    monkeypatch.setattr("walkie.weather.fetch_forecast", lambda *a, **k: None)
    result = refresh_if_stale(cache, 6.3, 8.1, "Africa/Lagos")
    assert result is not None
    assert result.summary == "stale-but-usable"


def test_weather_fingerprint_stable_and_discriminating():
    base = Weather(
        summary="rain", temperature_2m=26.0, precipitation_probability_max=40
    )
    jittered = replace(base, temperature_2m=26.4)
    assert weather_fingerprint(base) == weather_fingerprint(jittered)
    drier = replace(base, precipitation_probability_max=5)
    assert weather_fingerprint(base) != weather_fingerprint(drier)
    assert weather_fingerprint(None) == "unavailable"


def test_weather_line_offline_and_online():
    assert weather_line(None) == "weather unavailable (offline)"
    line = weather_line(
        Weather(
            summary="overcast",
            temperature_2m=27.8,
            temperature_2m_max=31.2,
            precipitation_probability_max=40,
            wind_speed_10m=9.1,
        )
    )
    assert "overcast, 27.8C" in line
    assert "rain chance 40%" in line
