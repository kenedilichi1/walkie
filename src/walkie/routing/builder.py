"""Offline route builder: local OSM extract -> closed walking loop -> walk.gpx.

Reads the region's .pbf with osmium (one pass, bbox around the start point),
builds an OSMnx street graph (cached in cache/routes/ so the slow scan happens
once), finds a start->out->back-to-start loop sized to the planned duration,
and exports a timestamped GPX track that fits the walk window.

Everything runs offline: no Overpass, no network after `make region`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import gpxpy
import networkx as nx
import osmium
import osmnx as ox
import pandas as pd

from walkie import clock, config
from walkie.geo import haversine_m
from walkie.log import get_logger
from walkie.models import Plan, TodayPlan, UserPlan
from walkie.routing import RouteError
from walkie.storage import read_json

log = get_logger("route")

SCAN_RADIUS_M = 2000.0
LOOP_CANDIDATES = 8
GOOD_ENOUGH = 0.05  # within 5% of target: stop searching
EXCLUDE_HIGHWAY = frozenset(
    {"motorway", "motorway_link", "trunk", "trunk_link", "construction",
     "proposed", "raceway", "escape", "bus_guideway"}
)
NO_ACCESS = frozenset({"no", "private"})


@dataclass(frozen=True)
class RouteResult:
    gpx_path: Path
    distance_m: float
    duration_minutes: int
    start_time: datetime
    source: str


class _Scanner(osmium.SimpleHandler):
    """One pass over the extract: in-bbox node coords + walkable ways."""

    def __init__(self, lat: float, lon: float, radius_m: float) -> None:
        super().__init__()
        dlat = radius_m / 111_320.0
        dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
        self.lat0, self.lat1 = lat - dlat, lat + dlat
        self.lon0, self.lon1 = lon - dlon, lon + dlon
        self.coords: dict[int, tuple[float, float]] = {}
        self.ways: list[tuple[int, list[int], str]] = []

    def node(self, n: object) -> None:
        loc = n.location  # type: ignore[attr-defined]
        if not loc.valid():
            return
        la, lo = loc.lat, loc.lon
        if self.lat0 <= la <= self.lat1 and self.lon0 <= lo <= self.lon1:
            self.coords[n.id] = (la, lo)  # type: ignore[attr-defined]

    def way(self, w: object) -> None:
        tags = {t.k: t.v for t in w.tags}  # type: ignore[attr-defined]
        highway = tags.get("highway")
        if highway is None or highway in EXCLUDE_HIGHWAY or _blocked(tags):
            return
        ids = [ref.ref for ref in w.nodes]  # type: ignore[attr-defined]
        if len(ids) >= 2 and all(i in self.coords for i in ids):
            self.ways.append((w.id, ids, highway))  # type: ignore[attr-defined]


def _blocked(tags: dict[str, str]) -> bool:
    if "foot" in tags:
        return tags["foot"] in NO_ACCESS
    return tags.get("access", "") in NO_ACCESS


def _cache_paths(cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / "streets.graphml", cache_dir / "streets.meta.json"


def _expected_meta(pbf_path: Path, lat: float, lon: float) -> dict:
    stat = pbf_path.stat()
    return {
        "pbf": str(pbf_path),
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "lat": lat,
        "lon": lon,
        "radius_m": SCAN_RADIUS_M,
    }


def _cache_matches(meta_path: Path, expected: dict) -> bool:
    try:
        return json.loads(meta_path.read_text()) == expected
    except (OSError, ValueError):
        return False


def load_street_graph(
    pbf_path: Path,
    lat: float,
    lon: float,
    cache_dir: Path,
    refresh: bool = False,
) -> nx.MultiDiGraph:
    """Walkable street graph around (lat, lon); scans the extract once, then caches."""
    if not pbf_path.exists():
        raise RouteError(f"{pbf_path} not found — run: make region")
    graph_path, meta_path = _cache_paths(cache_dir)
    expected = _expected_meta(pbf_path, lat, lon)
    if not refresh and graph_path.exists() and _cache_matches(meta_path, expected):
        graph = ox.io.load_graphml(graph_path)
        log.info(f"Street graph from cache ({len(graph)} nodes)")
        return graph
    log.info("Scanning OSM extract for walkable streets (first run takes minutes)...")
    scanner = _Scanner(lat, lon, SCAN_RADIUS_M)
    try:
        scanner.apply_file(str(pbf_path), locations=False)
    except (RuntimeError, OSError) as exc:
        raise RouteError(f"could not read {pbf_path}: {exc}") from exc
    graph = _graph_from_scanner(scanner)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ox.io.save_graphml(graph, graph_path)
    meta_path.write_text(json.dumps(expected))
    log.info(f"Street graph built ({len(graph)} nodes) and cached")
    return graph


def _graph_from_scanner(scanner: _Scanner) -> nx.MultiDiGraph:
    rows: list[dict] = []
    index: list[tuple[int, int, int]] = []
    used: set[int] = set()
    keys: dict[tuple[int, int], int] = {}
    for way_id, ids, highway in scanner.ways:
        for a, b in zip(ids, ids[1:], strict=False):
            if a == b:
                continue
            used.update((a, b))
            length = haversine_m(*scanner.coords[a], *scanner.coords[b])
            for u, v in ((a, b), (b, a)):
                key = keys.get((u, v), 0)
                keys[(u, v)] = key + 1
                rows.append({"osmid": way_id, "highway": highway, "length": length})
                index.append((u, v, key))
    if not rows:
        raise RouteError("no walkable streets near this location — check region data")
    node_ids = sorted(used)
    nodes = gpd.GeoDataFrame(
        {
            "osmid": node_ids,
            "x": [scanner.coords[i][1] for i in node_ids],
            "y": [scanner.coords[i][0] for i in node_ids],
        },
        index=pd.Index(node_ids, name="osmid"),
    )
    edges = gpd.GeoDataFrame(
        rows,
        index=pd.MultiIndex.from_tuples(index, names=["u", "v", "key"]),
    )
    return ox.graph_from_gdfs(nodes, edges, graph_attrs={"crs": "EPSG:4326"})


def _reconstruct(pred: dict, node: int, source: int) -> list[int]:
    path: list[int] = [node]
    while path[-1] != source:
        path.append(pred[path[-1]][0])
    path.reverse()
    return path


def _path_length(graph: nx.MultiDiGraph, path: list[int]) -> float:
    total = 0.0
    for u, v in zip(path, path[1:], strict=False):
        data = graph.get_edge_data(u, v)
        total += min(edge["length"] for edge in data.values())
    return total


def _disjoint_return(
    graph: nx.MultiDiGraph, path: list[int], source: int, dest: int
) -> list[int] | None:
    """Shortest source->dest path avoiding every street used by `path`."""
    reduced = graph.copy()
    blocked: set[tuple[int, int, int]] = set()
    for u, v in zip(path, path[1:], strict=False):
        for a, b in ((u, v), (v, u)):
            existing = reduced.get_edge_data(a, b) or {}
            blocked.update((a, b, key) for key in existing)
    reduced.remove_edges_from(blocked)
    try:
        return nx.shortest_path(reduced, source, dest, weight="length")
    except nx.NetworkXNoPath:
        return None


def build_loop(
    graph: nx.MultiDiGraph, lat: float, lon: float, target_m: float
) -> tuple[list[int], float]:
    """Closed start->...->start loop near `target_m` meters (node id list, length)."""
    try:
        source = ox.distance.nearest_nodes(graph, lon, lat)
    except (ValueError, KeyError) as exc:
        raise RouteError("no streets near this location") from exc
    pred, dist = nx.dijkstra_predecessor_and_distance(graph, source, weight="length")
    candidates = sorted(
        (n for n, d in dist.items() if 0.15 * target_m <= d <= 0.7 * target_m),
        key=lambda n: (abs(2 * dist[n] - target_m), n),
    )
    if not candidates:
        return _fallback_out_and_back(pred, dist, source, target_m)
    best: tuple[float, list[int], float] | None = None
    for dest in candidates[:LOOP_CANDIDATES]:
        out = _reconstruct(pred, dest, source)
        loop, length = out + out[-2::-1], 2 * dist[dest]
        back = _disjoint_return(graph, out, source, dest)
        if back is not None:
            loop = out + back[::-1][1:]
            length = dist[dest] + _path_length(graph, back)
        score = abs(length - target_m)
        if best is None or score < best[0]:
            best = (score, loop, length)
        if score <= GOOD_ENOUGH * target_m:
            break
    assert best is not None  # candidates non-empty above
    return best[1], best[2]


def _fallback_out_and_back(
    pred: dict, dist: dict, source: int, target_m: float
) -> tuple[list[int], float]:
    reachable = [n for n, d in dist.items() if n != source and d > 0]
    if not reachable:
        raise RouteError("no streets near this location — check region data")
    far = max(reachable, key=lambda n: (dist[n], -n))
    out = _reconstruct(pred, far, source)
    loop = out + out[-2::-1]
    if dist[far] < 0.35 * target_m:
        log.warning(
            f"street network too small for a {target_m:.0f} m loop "
            f"(best out-and-back: {2 * dist[far]:.0f} m)"
        )
    return loop, 2 * dist[far]


def export_gpx(
    graph: nx.MultiDiGraph,
    loop: list[int],
    start_time: datetime,
    duration_minutes: int,
    out_path: Path,
) -> tuple[float, datetime]:
    """Write the loop as a GPX track; timestamps span exactly the walk window."""
    coords = [(graph.nodes[n]["y"], graph.nodes[n]["x"]) for n in loop]
    cumulative = [0.0]
    for (la1, lo1), (la2, lo2) in zip(coords, coords[1:], strict=False):
        cumulative.append(cumulative[-1] + haversine_m(la1, lo1, la2, lo2))
    total = cumulative[-1]
    if total <= 0:
        raise RouteError("computed an empty loop")
    span_s = duration_minutes * 60
    gpx = gpxpy.gpx.GPX()
    gpx.version = "1.1"
    gpx.creator = "walkie"
    track = gpxpy.gpx.GPXTrack(name="walkie loop")
    segment = gpxpy.gpx.GPXTrackSegment()
    for (la, lo), walked in zip(coords, cumulative, strict=True):
        point = gpxpy.gpx.GPXTrackPoint(latitude=la, longitude=lo)
        point.time = start_time + timedelta(seconds=span_s * walked / total)
        segment.points.append(point)
    track.segments.append(segment)
    gpx.tracks.append(track)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(gpx.to_xml())
    return total, start_time


def _start_time(hhmm: str, timezone_name: str) -> datetime | None:
    try:
        hour, minute = (int(part) for part in hhmm.split(":", 1))
        return datetime.combine(
            clock.now().date(), dtime(hour, minute), tzinfo=ZoneInfo(timezone_name)
        )
    except (ValueError, TypeError, KeyError):
        return None


def resolve_walk_window(
    timezone_name: str,
    today_plan_path: Path = config.TODAY_PLAN_PATH,
    plan_path: Path = config.PLAN_PATH,
    user_plan_path: Path = config.USER_PLAN_PATH,
) -> tuple[int, datetime, str]:
    """(duration_minutes, start_time, source): today_plan -> plan -> user_plan."""
    today = clock.now().date().isoformat()
    today_data = read_json(today_plan_path)
    if today_data:
        proposal = TodayPlan.from_dict(today_data)
        if proposal.for_date == today:
            start = _start_time(proposal.suggested_time, timezone_name)
            if start:
                return proposal.duration_minutes, start, "today_plan"
    plan_data = read_json(plan_path)
    if plan_data:
        plan = Plan.from_dict(plan_data)
        if plan.for_date == today:
            start = _start_time(plan.window_start, timezone_name)
            if start:
                return plan.duration_minutes, start, "plan"
    base = UserPlan.from_dict(read_json(user_plan_path) or {})
    start = _start_time(base.preferred_time, timezone_name) or clock.now()
    return base.duration_minutes, start, "user_plan"


def build_route(
    pbf_path: Path,
    lat: float,
    lon: float,
    timezone_name: str,
    minutes: int | None = None,
    refresh: bool = False,
    cache_dir: Path = config.CACHE_DIR / "routes",
    out_path: Path = config.DEFAULT_WALK_GPX,
    window: tuple[int, datetime, str] | None = None,
) -> RouteResult:
    """Full pipeline: graph -> loop-sized GPX; returns what the CLI reports.

    `window` injects (minutes, start_time, source) directly — tests use it to
    avoid reading real config files.
    """
    if window is not None:
        minutes, start_time, source = window
    elif minutes is None:
        minutes, start_time, source = resolve_walk_window(timezone_name)
    else:
        _, start_time, source = resolve_walk_window(timezone_name)
    if minutes <= 0:
        raise RouteError(f"duration must be positive, got {minutes}")
    graph = load_street_graph(pbf_path, lat, lon, cache_dir, refresh=refresh)
    target_m = minutes * 60 * config.WALKING_SPEED_MPS
    loop, length = build_loop(graph, lat, lon, target_m)
    if abs(length - target_m) > 0.15 * target_m:
        log.warning(f"loop is {length:.0f} m, target was {target_m:.0f} m")
    total, _ = export_gpx(graph, loop, start_time, minutes, out_path)
    pace = total / minutes
    log.info(
        f"Route: {total:.0f} m loop, {minutes} min from {start_time:%H:%M} "
        f"({source}, {pace:.0f} m/min pace) -> {out_path}"
    )
    log.info("Load it in OsmAnd, or narrate it: walkie voice")
    return RouteResult(out_path, total, minutes, start_time, source)
