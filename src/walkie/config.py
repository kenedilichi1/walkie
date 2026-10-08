"""Config paths, settings loading, and config-file helpers.

load_settings() validates the location loudly (ConfigError) instead of
silently falling back to null island. Path constants live here so no other
module hardcodes ROOT-relative paths.
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from walkie import clock, policy
from walkie.models import UserPlan
from walkie.storage import read_record, write_json

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
OUTPUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
USER_PLAN_PATH = CONFIG_DIR / "user_plan.json"
QUOTES_PATH = CONFIG_DIR / "quotes.txt"
PROPOSAL_PATH = OUTPUT_DIR / "proposal.json"
TODAY_PLAN_PATH = OUTPUT_DIR / "today_plan.json"
REMINDER_STATE_PATH = OUTPUT_DIR / "reminder_state.json"
PLAN_PATH = OUTPUT_DIR / "plans" / "plan.json"
ROUTES_DIR = OUTPUT_DIR / "routes"
WALK_AUDIO_PATH = OUTPUT_DIR / "audio" / "walk_audio.mp3"
DEFAULT_WALK_GPX = ROUTES_DIR / "walk.gpx"

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_WEATHER_CACHE = "cache/weather_today.json"
DEFAULT_QUOTE = "Stand up from your computer."
DEFAULT_VOICE_MODEL = "data/voices/en_US-lessac-medium.onnx"
WALKING_SPEED_MPS = 1.35


class ConfigError(Exception):
    """Invalid or missing configuration; the message is user-facing."""


@dataclass(frozen=True)
class Settings:
    lat: float
    lon: float
    timezone: str
    forecast_url: str
    weather_cache: Path
    ollama_host: str
    ollama_model: str
    voice_model: Path
    pbf: Path | None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"{path} missing — run: make setup")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} is not a valid settings file")
    return data


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _validate_location(lat: float, lon: float) -> None:
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ConfigError(f"location out of range (lat={lat}, lon={lon})")
    if math.hypot(lat, lon) < 1e-9:
        # within ~0.1 mm of (0,0): the example placeholders, not a real place
        raise ConfigError("location not configured — run: make region")


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    data = _read_yaml(path)
    location = data.get("location") or {}
    weather_cfg = data.get("weather") or {}
    ollama_cfg = data.get("ollama") or {}
    voice_cfg = data.get("voice") or {}
    region_cfg = data.get("region") or {}
    pbf_raw = region_cfg.get("pbf")

    try:
        lat = float(location.get("lat", 0.0))
        lon = float(location.get("lon", 0.0))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid coordinates in {path}") from exc
    _validate_location(lat, lon)

    return Settings(
        lat=lat,
        lon=lon,
        timezone=str(location.get("timezone") or "UTC"),
        forecast_url=str(weather_cfg.get("forecast_url") or DEFAULT_FORECAST_URL),
        weather_cache=_resolve(str(weather_cfg.get("cache") or DEFAULT_WEATHER_CACHE)),
        ollama_host=str(ollama_cfg.get("host") or DEFAULT_OLLAMA_HOST),
        ollama_model=str(ollama_cfg.get("model") or DEFAULT_OLLAMA_MODEL),
        voice_model=_resolve(str(voice_cfg.get("model") or DEFAULT_VOICE_MODEL)),
        pbf=_resolve(str(pbf_raw)) if pbf_raw else None,
    )


def load_ollama_config(path: Path = SETTINGS_PATH) -> tuple[str, str]:
    """Host/model for the local LLM; never fails on location config."""
    try:
        data = _read_yaml(path)
    except ConfigError:
        return DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_MODEL
    ollama_cfg = data.get("ollama") or {}
    return (
        str(ollama_cfg.get("host") or DEFAULT_OLLAMA_HOST),
        str(ollama_cfg.get("model") or DEFAULT_OLLAMA_MODEL),
    )


def load_quotes(path: Path = QUOTES_PATH) -> list[str]:
    """Editable quotes, skipping blanks and # comments."""
    if not path.exists():
        return [DEFAULT_QUOTE]
    quotes = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return quotes or [DEFAULT_QUOTE]


def pick_quote(path: Path = QUOTES_PATH) -> str:
    return secrets.choice(load_quotes(path))


def load_user_plan(path: Path = USER_PLAN_PATH) -> UserPlan:
    """Load the user's preferences; fail loudly on anything unusable.

    This is the boundary for hand-edited data, so unlike the cached records
    (tolerant by design) a bad time or duration is an error with a remedy.
    """
    plan = read_record(path, UserPlan.from_dict)
    if plan is None:
        raise ConfigError(f"{path} missing or unreadable — run: walkie wizard")
    if clock.parse_hhmm(plan.preferred_time) is None:
        raise ConfigError(
            f"{path}: preferred_time {plan.preferred_time!r} is not HH:MM — "
            "run: walkie wizard"
        )
    if not (
        policy.USER_MIN_DURATION
        <= plan.duration_minutes
        <= policy.USER_MAX_DURATION
    ):
        raise ConfigError(
            f"{path}: duration_minutes {plan.duration_minutes} outside "
            f"{policy.USER_MIN_DURATION}-{policy.USER_MAX_DURATION} min — "
            "run: walkie wizard"
        )
    return plan


def save_user_plan(plan: UserPlan, path: Path = USER_PLAN_PATH) -> None:
    write_json(path, plan.to_dict())
