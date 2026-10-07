"""Step 5: offline route builder — fixture grid PBF -> loop -> walk.gpx.

Grid fixture: 6x6 nodes at ~222 m spacing around (6.0, 8.0), horizontal +
vertical residential ways (like real blocks). An 11-minute target (891 m)
resolves to one square block (888 m) closing at the start node.
"""

from __future__ import annotations

import math
from datetime import datetime
from datetime import timezone as tz
from pathlib import Path

import gpxpy
import networkx as nx
import osmium
import pytest

from walkie import config
from walkie.media.voice import AudioSpec, build_walk_audio, parse_walk
from walkie.routing import RouteError, builder

LAT0, LON0 = 6.0, 8.0
STEP = 0.002  # ~222 m
START = datetime(2026, 10, 7, 16, 30, tzinfo=tz.utc)


def write_grid_pbf(path: Path, tags: dict[str, str] | None = None) -> Path:
    """Write a 6x6 street grid; ways are one row/column each."""
    tags = tags or {"highway": "residential"}
    path.unlink(missing_ok=True)
    writer = osmium.SimpleWriter(str(path))
    node_id = 1
    coords: dict[tuple[int, int], int] = {}
    lon_step = STEP / math.cos(math.radians(LAT0))
    for r in range(6):
        for c in range(6):
            lat = LAT0 + r * STEP
            lon = LON0 + c * lon_step
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={})
            )
            coords[(r, c)] = node_id
            node_id += 1
    way_id = 100
    for r in range(6):  # east-west rows
        writer.add_way(
            osmium.osm.mutable.Way(
                id=way_id, tags=tags, nodes=[coords[(r, c)] for c in range(6)]
            )
        )
        way_id += 1
    for c in range(6):  # north-south columns
        writer.add_way(
            osmium.osm.mutable.Way(
                id=way_id, tags=tags, nodes=[coords[(r, c)] for r in range(6)]
            )
        )
        way_id += 1
    writer.close()
    return path


def route(tmp_path: Path, minutes: int = 11, **kwargs) -> builder.RouteResult:
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    kwargs.setdefault("cache_dir", tmp_path / "cache")
    return builder.build_route(
        pbf,
        LAT0,
        LON0,
        "Africa/Lagos",
        minutes=minutes,
        out_path=tmp_path / "walk.gpx",
        window=(minutes, START, "user_plan"),
        **kwargs,
    )


def read_points(path: Path):
    gpx = gpxpy.parse(path.read_text())
    return gpx.tracks[0].segments[0].points


def test_graph_from_fixture_grid(tmp_path):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    graph = builder.load_street_graph(pbf, LAT0, LON0, tmp_path / "cache")
    assert len(graph) == 36
    assert graph.number_of_edges() == 120  # 60 segments x 2 directions


def test_graph_excludes_motorway_and_foot_no(tmp_path):
    pbf = tmp_path / "mixed.osm.pbf"
    writer = osmium.SimpleWriter(str(pbf))
    ids = {}
    node_id = 1
    for r in range(3):
        for c in range(3):
            writer.add_node(
                osmium.osm.mutable.Node(
                    id=node_id,
                    location=(LON0 + c * STEP, LAT0 + r * STEP),
                    tags={},
                )
            )
            ids[(r, c)] = node_id
            node_id += 1
    way_id = 100
    for tags in ({"highway": "residential"}, {"highway": "footway"}):
        writer.add_way(
            osmium.osm.mutable.Way(
                id=way_id, tags=tags, nodes=[ids[(0, c)] for c in range(3)]
            )
        )
        way_id += 1
    for tags in ({"highway": "motorway"}, {"highway": "residential", "foot": "no"}):
        writer.add_way(
            osmium.osm.mutable.Way(
                id=way_id, tags=tags, nodes=[ids[(2, c)] for c in range(3)]
            )
        )
        way_id += 1
    writer.close()
    graph = builder.load_street_graph(pbf, LAT0, LON0, tmp_path / "cache")
    assert graph.number_of_edges() == 8  # 4 kept segments x 2 dirs


def test_missing_pbf_raises(tmp_path):
    with pytest.raises(RouteError, match="make region"):
        builder.load_street_graph(tmp_path / "nope.pbf", LAT0, LON0, tmp_path / "cache")


def test_build_loop_closes_and_hits_target(tmp_path):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    graph = builder.load_street_graph(pbf, LAT0, LON0, tmp_path / "cache")
    target = 11 * 60 * config.WALKING_SPEED_MPS  # ~891 m
    loop, length = builder.build_loop(graph, LAT0, LON0, target)
    assert loop[0] == loop[-1]
    assert len(set(loop)) == len(loop) - 1  # only the closing node repeats
    assert length == pytest.approx(target, rel=0.1)
    assert length == pytest.approx(888, rel=0.05)


def test_build_loop_single_node_graph_rejected():
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, osmid=1, x=LON0, y=LAT0)
    with pytest.raises(RouteError, match="no streets"):
        builder.build_loop(graph, LAT0, LON0, 891.0)


def test_route_writes_gpx_with_window_fit(tmp_path):
    result = route(tmp_path, minutes=11)
    assert result.gpx_path.exists()
    assert result.source == "user_plan"
    assert result.duration_minutes == 11
    assert result.start_time.strftime("%H:%M") == "16:30"
    points = read_points(result.gpx_path)
    assert (points[0].latitude, points[0].longitude) == pytest.approx(
        (points[-1].latitude, points[-1].longitude), abs=1e-7
    )
    span = (points[-1].time - points[0].time).total_seconds()
    assert span == pytest.approx(11 * 60, abs=1)  # fits the window exactly
    assert result.distance_m == pytest.approx(888, rel=0.1)


def test_route_is_deterministic_across_runs(tmp_path):
    route(tmp_path, minutes=11)
    first = (tmp_path / "walk.gpx").read_bytes()
    route(tmp_path, minutes=11)
    assert (tmp_path / "walk.gpx").read_bytes() == first


def test_cache_skips_rescan_and_refresh_forces_it(tmp_path, monkeypatch):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    calls: list[str] = []
    original = builder._Scanner.apply_file

    def counting(self, *args, **kwargs):
        calls.append(str(args[0]) if args else "?")
        return original(self, *args, **kwargs)

    def run(**kwargs):
        return builder.build_route(
            pbf,
            LAT0,
            LON0,
            "Africa/Lagos",
            minutes=11,
            out_path=tmp_path / "walk.gpx",
            window=(11, START, "test"),
            cache_dir=tmp_path / "cache",
            **kwargs,
        )

    monkeypatch.setattr(builder._Scanner, "apply_file", counting)
    run()
    assert len(calls) == 1
    run()  # same pbf, unchanged: cached
    assert len(calls) == 1
    run(refresh=True)
    assert len(calls) == 2


def test_resolve_prefers_today_plan(tmp_path):
    from walkie import clock

    today = clock.now().date().isoformat()
    (tmp_path / "today.json").write_text(
        f'{{"for_date": "{today}", "suggested_time": "17:00", "duration_minutes": 45}}'
    )
    (tmp_path / "plan.json").write_text(
        f'{{"for_date": "{today}", "window_start": "15:30", "duration_minutes": 30}}'
    )
    (tmp_path / "user.json").write_text('{"duration_minutes": 20}')
    minutes, start, source = builder.resolve_walk_window(
        "Africa/Lagos",
        today_plan_path=tmp_path / "today.json",
        plan_path=tmp_path / "plan.json",
        user_plan_path=tmp_path / "user.json",
    )
    assert (minutes, source) == (45, "today_plan")
    assert start.strftime("%H:%M") == "17:00"


def test_resolve_falls_back_to_plan_then_user_plan(tmp_path):
    from walkie import clock

    today = clock.now().date().isoformat()
    empty = tmp_path / "none.json"
    (tmp_path / "plan.json").write_text(
        f'{{"for_date": "{today}", "window_start": "15:30", "duration_minutes": 30}}'
    )
    (tmp_path / "user.json").write_text(
        '{"duration_minutes": 20, "preferred_time": "16:30"}'
    )
    minutes, _, source = builder.resolve_walk_window(
        "Africa/Lagos", empty, tmp_path / "plan.json", tmp_path / "user.json"
    )
    assert (minutes, source) == (30, "plan")
    minutes, start, source = builder.resolve_walk_window(
        "Africa/Lagos", empty, empty, tmp_path / "user.json"
    )
    assert (minutes, source) == (20, "user_plan")
    assert start.strftime("%H:%M") == "16:30"


def test_resolve_skips_plan_from_another_day(tmp_path):

    (tmp_path / "plan.json").write_text(
        '{"for_date": "2000-01-01", "window_start": "15:30", "duration_minutes": 30}'
    )
    (tmp_path / "user.json").write_text(
        '{"duration_minutes": 20, "preferred_time": "07:00"}'
    )
    minutes, _, source = builder.resolve_walk_window(
        "Africa/Lagos",
        tmp_path / "none.json",
        tmp_path / "plan.json",
        tmp_path / "user.json",
    )
    assert (minutes, source) == (20, "user_plan")


def test_voice_narrates_route_gpx(tmp_path):
    result = route(tmp_path, minutes=11)
    walk = parse_walk(result.gpx_path)
    assert walk.loop_seconds == pytest.approx(660, abs=1)
    assert len(walk.turns) == 3  # one square block: three corners
    assert all(t.instruction.startswith("Turn") for t in walk.turns)

    audio = build_walk_audio(
        result.gpx_path,
        out_path=tmp_path / "walk_audio.mp3",
        synth=lambda text: (AudioSpec(22050, 2, 1), b"\x01\x00" * 1000),
    )
    assert audio.cues == 5
    assert audio.loop_seconds == pytest.approx(660, abs=1)


def test_rejects_bad_minutes(tmp_path):
    pbf = write_grid_pbf(tmp_path / "grid.osm.pbf")
    with pytest.raises(RouteError, match="positive"):
        builder.build_route(
            pbf,
            LAT0,
            LON0,
            "Africa/Lagos",
            minutes=0,
            cache_dir=tmp_path / "cache",
            out_path=tmp_path / "walk.gpx",
        )


PBF_FILES = sorted(config.ROOT.glob("data/osm/*.pbf"))


@pytest.mark.skipif(not PBF_FILES, reason="no OSM extract (run: make region)")
def test_live_route_on_real_extract(tmp_path):
    settings = config.load_settings()
    assert settings.pbf is not None
    result = builder.build_route(
        settings.pbf,
        settings.lat,
        settings.lon,
        settings.timezone,
        minutes=10,
        out_path=tmp_path / "live.gpx",  # never clobber the user's walk.gpx
    )
    points = read_points(result.gpx_path)
    assert (points[0].latitude, points[0].longitude) == pytest.approx(
        (points[-1].latitude, points[-1].longitude), abs=1e-6
    )
    span = (points[-1].time - points[0].time).total_seconds()
    assert span == pytest.approx(600, abs=1)
    assert result.distance_m > 500
