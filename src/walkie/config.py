"""Config paths, settings loading, and config-file helpers.

load_settings() validates the location loudly (ConfigError) instead of
silently falling back to null island. Path constants live here so no other
module hardcodes ROOT-relative paths.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import yaml

from walkie.models import UserPlan
from walkie.storage import read_json, write_json

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

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_WEATHER_CACHE = "cache/weather_today.json"
DEFAULT_QUOTE = "Stand up from your computer."


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


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"{path} missing — run: make setup")
    try:
        data = yaml.safe_load(path.read_text()) or {}
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
    if lat == 0.0 and lon == 0.0:
        raise ConfigError("location not configured — run: make region")


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    data = _read_yaml(path)
    location = data.get("location") or {}
    weather_cfg = data.get("weather") or {}
    ollama_cfg = data.get("ollama") or {}

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
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return quotes or [DEFAULT_QUOTE]


def pick_quote(path: Path = QUOTES_PATH) -> str:
    return random.choice(load_quotes(path))


def load_user_plan(path: Path = USER_PLAN_PATH) -> UserPlan:
    data = read_json(path)
    if data is None:
        raise ConfigError(f"{path} missing — run: walkie wizard")
    return UserPlan.from_dict(data)


def save_user_plan(plan: UserPlan, path: Path = USER_PLAN_PATH) -> None:
    write_json(path, plan.to_dict())
