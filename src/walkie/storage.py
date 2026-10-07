"""Small JSON persistence helpers (read-optional, atomic write)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def read_json(path: Path) -> dict | None:
    """Read a JSON object; returns None for missing/corrupt files."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict) -> None:
    """Write JSON atomically (tmp file + rename) so crashes can't truncate."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
