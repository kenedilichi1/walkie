"""Desktop notifications and LAN phone sync."""

from __future__ import annotations


class SyncError(Exception):
    """Server could not start (port busy, missing output directory)."""
