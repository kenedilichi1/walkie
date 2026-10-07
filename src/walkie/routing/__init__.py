"""Offline route builder: walking loop from the local OSM extract."""

from __future__ import annotations


class RouteError(Exception):
    """Route generation failed; the message is user-facing."""
