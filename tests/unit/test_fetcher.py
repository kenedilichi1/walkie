from weather.fetcher import (
    compact_forecast,
    describe_weather_code,
    is_stale,
    refresh_if_stale,
    save_cache,
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
    assert result["summary"] == "overcast"
    assert result["temperature_2m_min"] == 24.0
    assert result["temperature_2m_max"] == 31.2
    assert result["precipitation_probability_max"] == 95
    assert result["timezone"] == "Africa/Lagos"


def test_is_stale_fresh_vs_old():
    import time

    assert not is_stale({"fetched_at": time.time()}, max_age_hours=2)
    assert is_stale({"fetched_at": time.time() - 7300}, max_age_hours=2)


def test_refresh_serves_fresh_cache_without_fetching(tmp_path, monkeypatch):
    cache = tmp_path / "weather.json"
    save_cache(cache, {"fetched_at": 10**10, "summary": "cached"})

    def fail_fetch(*args, **kwargs):
        raise AssertionError("should not fetch when cache is fresh")

    monkeypatch.setattr("weather.fetcher.fetch_forecast", fail_fetch)
    result = refresh_if_stale(cache, 6.3, 8.1, "Africa/Lagos")
    assert result["summary"] == "cached"


def test_refresh_refetches_when_stale(tmp_path, monkeypatch):
    cache = tmp_path / "weather.json"
    save_cache(cache, {"fetched_at": 0, "summary": "old"})

    def fake_fetch(lat, lon, tz, url):
        return {"fetched_at": 999, "summary": "fresh"}

    monkeypatch.setattr("weather.fetcher.fetch_forecast", fake_fetch)
    result = refresh_if_stale(cache, 6.3, 8.1, "Africa/Lagos")
    assert result["summary"] == "fresh"


def test_refresh_falls_back_to_stale_cache_when_offline(tmp_path, monkeypatch):
    cache = tmp_path / "weather.json"
    save_cache(cache, {"fetched_at": 0, "summary": "stale-but-usable"})
    monkeypatch.setattr("weather.fetcher.fetch_forecast", lambda *a, **k: None)
    result = refresh_if_stale(cache, 6.3, 8.1, "Africa/Lagos")
    assert result["summary"] == "stale-but-usable"
