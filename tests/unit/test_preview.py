"""Tests for the serve window's pure helpers (route projection, file status)."""

from pathlib import Path

from walkie.sync.preview import (
    FileStatus,
    fetch_tile,
    file_status,
    fit_map_frame,
    fit_projection,
    load_street_segments,
    mercator_world,
    parse_points,
    project,
    tile_cache_path,
)

GPX = """<?xml version="1.0"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="6.31600" lon="8.11600"></trkpt>
    <trkpt lat="6.31700" lon="8.11800"></trkpt>
    <trkpt lat="6.31800" lon="8.11600"></trkpt>
  </trkseg></trk>
</gpx>
"""


def _files(tmp_path: Path) -> tuple[tuple[str, str], ...]:
    (tmp_path / "present.gpx").write_bytes(b"x" * 2048)
    return (
        ("present.gpx", "a route"),
        ("absent.gpx", "missing one"),
    )


def test_file_status_reports_present_and_missing(tmp_path):
    statuses = file_status(tmp_path, _files(tmp_path))
    assert statuses == [
        FileStatus("present.gpx", "a route", True, 2.0),
        FileStatus("absent.gpx", "missing one", False, 0.0),
    ]


def test_parse_points_reads_track(tmp_path):
    gpx = tmp_path / "walk.gpx"
    gpx.write_text(GPX)
    points = parse_points(gpx)
    assert len(points) == 3
    assert points[0] == (6.316, 8.116)


def test_parse_points_missing_file_is_empty(tmp_path):
    assert parse_points(tmp_path / "nope.gpx") == []


def test_parse_points_invalid_file_is_empty(tmp_path):
    bad = tmp_path / "bad.gpx"
    bad.write_text("not gpx at all")
    assert parse_points(bad) == []


def test_project_empty_returns_empty():
    assert project([], 200, 200) == []


def test_project_fits_within_bounds_and_keeps_points():
    points = [(6.316, 8.116), (6.317, 8.118), (6.318, 8.116)]
    out = project(points, 200, 200, padding=10)
    assert len(out) == 3
    for x, y in out:
        assert 10 <= x <= 190
        assert 10 <= y <= 190


def test_project_is_north_up():
    # A point further north (higher lat) must sit higher (smaller y).
    north = project([(6.320, 8.116), (6.310, 8.116)], 100, 100)
    assert north[0][1] < north[1][1]


def test_project_aspect_ratio_preserved():
    # A loop twice as wide as tall keeps that ~2:1 shape.
    points = [(6.316, 8.116), (6.316, 8.118), (6.317, 8.118), (6.317, 8.116)]
    out = project(points, 200, 100, padding=0)
    xs = [p[0] for p in out]
    ys = [p[1] for p in out]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert width > height  # wider than tall, as the real loop is


def test_project_single_point_centres():
    out = project([(6.316, 8.116)], 100, 100, padding=10)
    assert out == [(50.0, 50.0)]


def test_load_street_segments_missing_graph_is_empty(tmp_path):
    assert load_street_segments(tmp_path / "nope.graphml") == []


def test_fit_projection_expand_grows_bounds():
    points = [(6.316, 8.116), (6.317, 8.118), (6.318, 8.116)]
    tight = fit_projection(points, 200, 200, padding=0)
    loose = fit_projection(points, 200, 200, padding=0, expand=2.0)
    # Expanding shrinks the on-screen subject (smaller scale), leaving margin.
    assert loose.scale < tight.scale


def test_shared_projection_keeps_streets_and_route_aligned():
    # One projection applied to a street and a route point that coincide in
    # the world must coincide on screen.
    route = [(6.316, 8.116), (6.318, 8.116)]
    proj = fit_projection(route, 200, 200)
    street_end = (6.316, 8.116)  # same as the route start
    assert proj.point(*street_end) == proj.point(*route[0])


def test_mercator_world_centre_is_half_world():
    # At the zoom-0 world centre (0N, 0E) the world pixel is the midpoint.
    wx, wy = mercator_world(0.0, 0.0, 0)
    assert abs(wx - 128.0) < 1e-6
    assert abs(wy - 128.0) < 1e-6


def test_mercator_world_increases_east_and_south():
    # Moving east increases x; moving south (lower lat) increases y.
    wx_west, _ = mercator_world(8.0, 6.3, 16)
    wx_east, _ = mercator_world(8.2, 6.3, 16)
    assert wx_east > wx_west
    _, wy_north = mercator_world(8.1, 6.4, 16)
    _, wy_south = mercator_world(8.1, 6.2, 16)
    assert wy_south > wy_north


def test_fit_map_frame_returns_none_for_bad_input():
    assert fit_map_frame([], 200, 200) is None
    assert fit_map_frame([(6.3, 8.1)], 10, 10) is None


def test_fit_map_frame_picks_zoom_and_centres_route():
    points = [(6.316, 8.116), (6.318, 8.118)]
    frame = fit_map_frame(points, 400, 400)
    assert frame is not None
    assert 3 <= frame.zoom <= 19
    # The route's midpoint should land near the centre of the viewport.
    mid_lat = (6.316 + 6.318) / 2
    mid_lon = (8.116 + 8.118) / 2
    sx, sy = frame.screen(mid_lat, mid_lon)
    assert abs(sx - 200) < 40
    assert abs(sy - 200) < 40


def test_fit_map_frame_tiles_cover_viewport():
    points = [(6.316, 8.116), (6.318, 8.118)]
    frame = fit_map_frame(points, 400, 400)
    assert frame is not None
    tiles = frame.tiles()
    # A 400x400 viewport is ~2x2 tiles; it must request at least one.
    assert len(tiles) >= 1
    for z, x, y in tiles:
        assert z == frame.zoom
        assert x >= 0 and y >= 0


def test_fetch_tile_reads_from_cache_without_network(tmp_path):
    # A tile already on disk is returned with no fetch at all.
    cached = tile_cache_path(tmp_path, 16, 34000, 26000)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"fake-png-bytes")
    assert fetch_tile(tmp_path, 16, 34000, 26000) == b"fake-png-bytes"


def test_fetch_tile_returns_none_when_offline(tmp_path):
    # No cache and no network -> None (caller falls back), never raises.
    assert fetch_tile(tmp_path, 16, 34000, 26000, timeout=0.2) is None
