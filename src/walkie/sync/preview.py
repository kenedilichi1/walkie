"""Pure helpers for the serve window: map projection, route, streets, file status.

No Qt here — these are the testable data functions the PyQt window paints.
Keeps `sync/` free of any GUI dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import gpxpy

from walkie.sync.server import FILES


@dataclass(frozen=True)
class FileStatus:
    """One served file's live state for the window's list."""

    rel: str
    note: str
    present: bool
    size_kb: float


def file_status(
    directory: Path,
    files: tuple[tuple[str, str], ...] = FILES,
) -> list[FileStatus]:
    """Present/size for each served file; cheap enough to poll every few seconds."""
    out: list[FileStatus] = []
    for rel, note in files:
        path = directory / rel
        if path.is_file():
            out.append(FileStatus(rel, note, True, path.stat().st_size / 1024))
        else:
            out.append(FileStatus(rel, note, False, 0.0))
    return out


def parse_points(gpx_path: Path) -> list[tuple[float, float]]:
    """(lat, lon) track points from a GPX file; empty when missing or unreadable."""
    try:
        track = gpxpy.parse(gpx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, gpxpy.gpx.GPXException):
        return []
    points: list[tuple[float, float]] = []
    for trk in track.tracks:
        for seg in trk.segments:
            for pt in seg.points:
                points.append((pt.latitude, pt.longitude))
    return points


def load_street_segments(
    graphml_path: Path,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """((lat, lon), (lat, lon)) street segments from the cached routing graph.

    This is the offline map: the same OSM extract the router builds the walk
    from. Empty when the graph is missing or unreadable (before the first
    route).
    """
    try:
        import networkx as nx

        graph = nx.read_graphml(graphml_path)
    except (OSError, ValueError, ImportError):
        return []
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for u, v in graph.edges():
        try:
            a = (float(graph.nodes[u]["y"]), float(graph.nodes[u]["x"]))
            b = (float(graph.nodes[v]["y"]), float(graph.nodes[v]["x"]))
        except (KeyError, TypeError, ValueError):
            continue
        segments.append((a, b))
    return segments


@dataclass(frozen=True)
class Projection:
    """A fitted lat/lon -> pixel transform; apply it to any point to keep
    streets and the route aligned in the same view."""

    lat_north: float
    lon_west: float
    cos_lat: float
    scale: float
    ox: float
    oy: float

    def point(self, lat: float, lon: float) -> tuple[float, float]:
        x = (lon - self.lon_west) * self.cos_lat
        y = self.lat_north - lat  # north up: higher lat -> smaller y
        return (self.ox + x * self.scale, self.oy + y * self.scale)


def _expand(
    points: list[tuple[float, float]], factor: float
) -> list[tuple[float, float]]:
    """Grow a point cloud's bounds by `factor` around its centre (for framing)."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_c = (min(lats) + max(lats)) / 2
    lon_c = (min(lons) + max(lons)) / 2
    return [
        (lat_c + (lat - lat_c) * factor, lon_c + (lon - lon_c) * factor)
        for lat, lon in points
    ] or points


def fit_projection(
    points: list[tuple[float, float]],
    width: int,
    height: int,
    padding: int = 14,
    expand: float = 1.0,
) -> Projection:
    """Fit (lat, lon) into a width x height box, aspect-correct, north up.

    Equirectangular with a cos(mean-latitude) longitude correction — plenty for
    a local walk, no map tiles or internet. Degenerate input (empty, a single
    point, or a straight line) is handled without dividing by zero. `expand`
    grows the bounds so the framed subject isn't flush against the edges.
    """
    if not points:
        return Projection(0.0, 0.0, 1.0, 1.0, padding, padding)
    if expand != 1.0:
        points = _expand(points, expand)
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_north = max(lats)
    lon_west = min(lons)
    cos_lat = math.cos(math.radians((min(lats) + max(lats)) / 2))
    xs = [(lon - lon_west) * cos_lat for lon in lons]
    ys = [lat_north - lat for lat in lats]
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)

    box_w = max(1, width - 2 * padding)
    box_h = max(1, height - 2 * padding)
    if x_span < 1e-12 and y_span < 1e-12:  # a single point: centre it
        return Projection(
            lat_north, lon_west, cos_lat, 1.0,
            padding + box_w / 2, padding + box_h / 2,
        )

    inf = float("inf")
    scale = min(
        box_w / x_span if x_span > 1e-12 else inf,
        box_h / y_span if y_span > 1e-12 else inf,
    )
    ox = padding + (box_w - x_span * scale) / 2
    oy = padding + (box_h - y_span * scale) / 2
    return Projection(lat_north, lon_west, cos_lat, scale, ox, oy)


def project(
    points: list[tuple[float, float]],
    width: int,
    height: int,
    padding: int = 14,
) -> list[tuple[float, float]]:
    """Fit a single point cloud into a box (thin wrapper over fit_projection)."""
    if not points:
        return []
    proj = fit_projection(points, width, height, padding)
    return [proj.point(lat, lon) for lat, lon in points]


# --- Real map tiles (web mercator) -----------------------------------------
#
# The street-graph lines were too abstract to read as a map. These helpers
# fetch real OpenStreetMap raster tiles and place them with the standard
# slippy-map maths so the route sits on a genuine map. Tiles are cached on
# disk, so a view is only fetched once and the window stays offline after.

TILE_PX = 256
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_USER_AGENT = "walkie/1.0 (personal walking-route preview)"


def mercator_world(
    lon: float, lat: float, zoom: int
) -> tuple[float, float]:
    """(x, y) in world pixels at `zoom` (web mercator, the slippy-map scheme)."""
    scale = TILE_PX * (2**zoom)
    wx = (lon + 180.0) / 360.0 * scale
    lat_r = math.radians(lat)
    wy = (
        (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
        / 2.0
        * scale
    )
    return wx, wy


@dataclass(frozen=True)
class MapFrame:
    """A fitted viewport onto the mercator world, at a fixed zoom.

    One transform maps any (lat, lon) to a screen pixel and tells which tiles
    to fetch, so tiles and the route are guaranteed to line up.
    """

    zoom: int
    origin_wx: float  # world-pixel x at the viewport's top-left
    origin_wy: float
    width: int
    height: int

    def screen(self, lat: float, lon: float) -> tuple[float, float]:
        wx, wy = mercator_world(lon, lat, self.zoom)
        return (wx - self.origin_wx, wy - self.origin_wy)

    def tiles(self) -> list[tuple[int, int, int]]:
        """(zoom, x, y) for every tile that overlaps the viewport."""
        wx2 = self.origin_wx + self.width
        wy2 = self.origin_wy + self.height
        tx1 = int(math.floor(self.origin_wx / TILE_PX))
        ty1 = int(math.floor(self.origin_wy / TILE_PX))
        tx2 = int(math.floor(wx2 / TILE_PX))
        ty2 = int(math.floor(wy2 / TILE_PX))
        return [
            (self.zoom, x, y)
            for x in range(tx1, tx2 + 1)
            for y in range(ty1, ty2 + 1)
        ]


def fit_map_frame(
    points: list[tuple[float, float]],
    width: int,
    height: int,
    fill: float = 0.7,
    max_zoom: int = 19,
) -> MapFrame | None:
    """Pick the highest zoom where the route still fits, centred in the box.

    Returns None for degenerate input (no points, or a panel too small to be
    meaningful) so the caller can fall back.
    """
    if not points or width < 32 or height < 32:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_n, lat_s = max(lats), min(lats)
    lon_w, lon_e = min(lons), max(lons)

    zoom = 3
    for z in range(max_zoom, 3, -1):
        wx1, wy1 = mercator_world(lon_w, lat_n, z)
        wx2, wy2 = mercator_world(lon_e, lat_s, z)
        if (wx2 - wx1) <= width * fill and (wy2 - wy1) <= height * fill:
            zoom = z
            break

    cx = (mercator_world(lon_w, lat_n, zoom)[0] + mercator_world(lon_e, lat_s, zoom)[0]) / 2
    cy = (mercator_world(lon_w, lat_n, zoom)[1] + mercator_world(lon_e, lat_s, zoom)[1]) / 2
    return MapFrame(
        zoom=zoom,
        origin_wx=cx - width / 2,
        origin_wy=cy - height / 2,
        width=width,
        height=height,
    )


def tile_cache_path(cache_dir: Path, z: int, x: int, y: int) -> Path:
    return cache_dir / str(z) / str(x) / f"{y}.png"


def fetch_tile(
    cache_dir: Path, z: int, x: int, y: int, timeout: float = 5.0
) -> bytes | None:
    """PNG bytes for one tile, from disk cache or the network.

    Best-effort: any failure (offline, bad tile, cache error) returns None so
    the caller can skip the tile rather than crash the preview.
    """
    path = tile_cache_path(cache_dir, z, x, y)
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError:
        pass

    import urllib.error
    import urllib.request

    url = TILE_URL.format(z=z, x=x, y=y)
    request = urllib.request.Request(url, headers={"User-Agent": TILE_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data: bytes = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    if not data:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        pass  # a failed cache write must not lose the fetched tile
    return data
