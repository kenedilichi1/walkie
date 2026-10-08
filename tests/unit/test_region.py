import argparse

import pytest

from walkie import region


def test_slugify():
    assert region.slugify("Nigeria") == "nigeria"
    assert region.slugify("South Africa") == "south-africa"
    assert region.slugify("  New York!! ") == "new-york"


def test_extract_candidates_prefers_subregion_then_country():
    candidates = region._extract_candidates(
        ["africa"], ["nigeria"], "ebonyi", "Ebonyi", "Nigeria"
    )
    assert candidates[0] == (
        "https://download.geofabrik.de/africa/nigeria/ebonyi-latest.osm.pbf",
        "Ebonyi",
    )
    assert candidates[-1] == (
        "https://download.geofabrik.de/africa/nigeria-latest.osm.pbf",
        "Nigeria",
    )


def test_find_extract_falls_back_to_country(monkeypatch):
    probed = []

    def fake_exists(url):
        probed.append(url)
        return url.endswith("nigeria-latest.osm.pbf")

    monkeypatch.setattr(region, "url_exists", fake_exists)
    url, name = region.find_extract("Nigeria", "ng", "Ebonyi", ["africa"])
    assert url.endswith("africa/nigeria-latest.osm.pbf")
    assert name == "Nigeria"
    # sub-region probe came first
    assert probed[0].endswith("africa/nigeria/ebonyi-latest.osm.pbf")


def test_find_extract_raises_when_nothing_found(monkeypatch):
    monkeypatch.setattr(region, "url_exists", lambda url: False)
    with pytest.raises(region.RegionError, match="Geofabrik"):
        region.find_extract("Atlantis", "", None, ["africa"])


def test_update_settings_pins_values_and_preserves_comments(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "# walkie settings\n"
        "region:\n"
        "  name: old-region\n"
        "  pbf: data/osm/old.pbf\n"
        "location:\n"
        "  lat: 0.0\n"
        "  lon: 0.0\n"
        "  timezone: UTC\n"
        "ollama:\n"
        "  model: llama3.2:3b\n"
    )
    region.update_settings(
        "data/osm/nigeria-latest.osm.pbf",
        "Nigeria",
        6.31625,
        -0.5,
        "Africa/Lagos",
        settings_path=settings,
    )
    text = settings.read_text()
    assert "# walkie settings" in text  # comment preserved
    assert "name: Nigeria" in text
    assert "pbf: data/osm/nigeria-latest.osm.pbf" in text
    assert "lat: 6.31625" in text
    assert "lon: -0.5" in text
    assert "timezone: Africa/Lagos" in text
    assert "model: llama3.2:3b" in text  # untouched keys survive


def test_update_settings_warns_on_missing_keys(tmp_path, caplog):
    settings = tmp_path / "settings.yaml"
    settings.write_text("unrelated:\n  key: value\n")
    with caplog.at_level("WARNING"):
        region.update_settings("x.pbf", "X", 1.0, 2.0, "UTC",
                               settings_path=settings)
    assert "keys not found" in caplog.text
    assert settings.read_text() == "unrelated:\n  key: value\n"


def test_format_coordinate_compact():
    assert region._format_coordinate(6.316250) == "6.31625"
    assert region._format_coordinate(-1.500000) == "-1.5"
    assert region._format_coordinate(0.0) == "0"


def test_scalar_needs_quotes():
    assert region._scalar_needs_quotes("a: b")
    assert region._scalar_needs_quotes("#x")
    assert region._scalar_needs_quotes(" padded ")
    assert not region._scalar_needs_quotes("Nigeria")
    assert not region._scalar_needs_quotes(6.3)


def test_detect_location_raises_region_error_when_all_sources_fail(monkeypatch):
    def boom(*args, **kwargs):
        raise region.requests.RequestException("offline")

    monkeypatch.setattr(region.requests, "get", boom)
    with pytest.raises(region.RegionError, match="--lat/--lon"):
        region.detect_location()


def test_resolve_location_manual_requires_name():
    args = argparse.Namespace(lat=1.0, lon=2.0, name=None, dry_run=False)
    with pytest.raises(region.RegionError, match="--name"):
        region._resolve_location(args)
    args.name = "Kenya"
    assert region._resolve_location(args) == (1.0, 2.0, "Kenya", "", "UTC")


_SETTINGS_TEMPLATE = (
    "# walkie settings\n"
    "region:\n"
    "  name: Nigeria\n"
    "  pbf: data/osm/nigeria-latest.osm.pbf\n"
    "location:\n"
    "  lat: 6.0\n"
    "  lon: 8.0\n"
    "  timezone: Africa/Lagos\n"
    "ollama:\n"
    "  model: llama3.2:3b\n"
)


def test_set_location_updates_coords_and_preserves_everything_else(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(_SETTINGS_TEMPLATE)
    region.set_location(6.31625, -0.5, settings_path=settings)
    text = settings.read_text()
    assert "# walkie settings" in text
    assert "lat: 6.31625" in text
    assert "lon: -0.5" in text
    assert "timezone: Africa/Lagos" in text  # untouched when tz not given
    assert "pbf: data/osm/nigeria-latest.osm.pbf" in text
    assert "model: llama3.2:3b" in text


def test_set_location_writes_timezone_when_given(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(_SETTINGS_TEMPLATE)
    region.set_location(6.31625, 8.11691, tz="Africa/Accra",
                        settings_path=settings)
    text = settings.read_text()
    assert "lat: 6.31625" in text
    assert "timezone: Africa/Accra" in text


def test_set_location_rejects_bad_points(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(_SETTINGS_TEMPLATE)
    with pytest.raises(region.RegionError, match="out of range"):
        region.set_location(91.0, 0.0, settings_path=settings)
    with pytest.raises(region.RegionError, match="0, 0"):
        region.set_location(0.0, 0.0, settings_path=settings)


def test_set_location_missing_settings_file(tmp_path):
    with pytest.raises(region.RegionError, match="not found"):
        region.set_location(6.0, 8.0, settings_path=tmp_path / "nope.yaml")


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_geocode_place_returns_first_hit(monkeypatch):
    def fake_get(url, **kwargs):
        assert "nominatim" in url
        return _Response(
            [{"lat": "6.31625", "lon": "8.11691", "display_name": "Riverside"}]
        )

    monkeypatch.setattr(region.requests, "get", fake_get)
    assert region.geocode_place("Riverside, Calabar") == (
        6.31625, 8.11691, "Riverside",
    )


def test_geocode_place_none_when_offline(monkeypatch):
    def boom(*args, **kwargs):
        raise region.requests.RequestException("offline")

    monkeypatch.setattr(region.requests, "get", boom)
    assert region.geocode_place("Riverside") is None


def test_geocode_place_blank_query_skips_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network touched")

    monkeypatch.setattr(region.requests, "get", boom)
    assert region.geocode_place("   ") is None


def test_geocode_place_rejects_out_of_range_hit(monkeypatch):
    monkeypatch.setattr(
        region.requests, "get",
        lambda *a, **k: _Response([{"lat": "999", "lon": "8.1"}]),
    )
    assert region.geocode_place("Somewhere") is None


def test_resolve_link_follows_short_link(monkeypatch):
    class _Redirect:
        url = "https://www.google.com/maps/place/X/@6.31625,8.11691,17z"

    monkeypatch.setattr(region.requests, "get", lambda *a, **k: _Redirect())
    assert region.resolve_link("https://maps.app.goo.gl/abc") == (6.31625, 8.11691)


def test_resolve_link_ignores_non_http():
    assert region.resolve_link("maps.app.goo.gl/abc") is None


def test_resolve_link_none_when_offline(monkeypatch):
    def boom(*args, **kwargs):
        raise region.requests.RequestException("offline")

    monkeypatch.setattr(region.requests, "get", boom)
    assert region.resolve_link("https://maps.app.goo.gl/abc") is None
