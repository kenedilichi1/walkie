"""Shared geo math and place parsing (pure functions, no I/O)."""

from __future__ import annotations

import math
import re
from urllib.parse import parse_qs, unquote, urlparse

_COORD_RE = re.compile(
    r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)
_AT_RE = re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)")
_OSM_FRAGMENT_RE = re.compile(
    r"^map=\d+(?:\.\d+)?/(-?\d{1,2}(?:\.\d+)?)/(-?\d{1,3}(?:\.\d+)?)"
)
_PAIR_KEYS = (("lat", "lon"), ("mlat", "mlon"))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(a))


def _point(lat: float, lon: float) -> tuple[float, float] | None:
    """(lat, lon) when it names a real place, else None."""
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None
    if math.hypot(lat, lon) < 1e-9:
        return None
    return (lat, lon)


def parse_coords(text: str) -> tuple[float, float] | None:
    """'6.31625, 8.11691' -> (6.31625, 8.11691); None unless it is one."""
    match = _COORD_RE.fullmatch(text)
    if not match:
        return None
    return _point(float(match.group(1)), float(match.group(2)))


def _query_point(query: dict[str, list[str]]) -> tuple[float, float] | None:
    """First query value that is itself a coordinate pair (any param name)."""
    for values in query.values():
        for value in values:
            point = parse_coords(value)
            if point:
                return point
    for lat_key, lon_key in _PAIR_KEYS:
        try:
            point = _point(float(query[lat_key][0]), float(query[lon_key][0]))
        except (KeyError, IndexError, ValueError):
            point = None
        if point:
            return point
    return None


def parse_map_link(url: str) -> tuple[float, float] | None:
    """Coordinates carried by a Google Maps / OSM / OsmAnd / geo: link."""
    text = url.strip()
    if text.startswith("geo:"):
        body = text[len("geo:"):]
        if "?" in body:
            return _query_point(parse_qs(body.split("?", 1)[1]))
        return parse_coords(unquote(body))

    parsed = urlparse(text)
    from_query = _query_point(parse_qs(parsed.query))
    if from_query:
        return from_query
    at = _AT_RE.search(unquote(text))
    if at:
        point = _point(float(at.group(1)), float(at.group(2)))
        if point:
            return point
    fragment = _OSM_FRAGMENT_RE.match(unquote(parsed.fragment))
    if fragment:
        point = _point(float(fragment.group(1)), float(fragment.group(2)))
        if point:
            return point
    for segment in unquote(parsed.path).split("/"):
        point = parse_coords(segment)
        if point:
            return point
    return None


def parse_place(text: str) -> tuple[float, float] | None:
    """Plain coordinates first, then a link; None when neither carries a point."""
    stripped = text.strip()
    if not stripped:
        return None
    return parse_coords(stripped) or parse_map_link(stripped)
