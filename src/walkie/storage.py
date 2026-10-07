"""Small JSON persistence helpers (read-optional, atomic write)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from walkie.log import get_logger

log = get_logger("storage")

T = TypeVar("T")


def read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object; None when missing or unusable (callers regenerate).

    A corrupt or unreadable file is logged so a first run and a broken file
    stay distinguishable in the output, even though both return None.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning(f"{path} is unreadable ({exc}) — treating as missing")
        return None
    if not isinstance(data, dict):
        log.warning(f"{path} does not hold a JSON object — treating as missing")
        return None
    return data


def read_record(path: Path, from_dict: Callable[[dict[str, Any]], T]) -> T | None:
    """Read a JSON file and rebuild its model; None when absent or unusable.

    The recurring `read_json` -> `from_dict` idiom in one place: read_json
    already logs why a file was unusable, and the from_dict parsers are
    tolerant by design (validation lives at the trust boundary instead).
    """
    data = read_json(path)
    return from_dict(data) if data is not None else None


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically (tmp file + rename) so crashes can't truncate."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
