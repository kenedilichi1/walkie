"""Shared route-test fixture: a 6x6 street grid OSM extract.

Grid: nodes at ~222 m spacing around (LAT0, LON0), horizontal + vertical
residential ways (like real blocks). An 11-minute target (891 m) resolves
to one square block (888 m) closing at the start node.

A plain helper module (not a test_*.py file) so both test_routing and
test_pipeline can use it without importing each other.
"""

from __future__ import annotations

import math
from pathlib import Path

import osmium

LAT0, LON0 = 6.0, 8.0
STEP = 0.002  # ~222 m


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
