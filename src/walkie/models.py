"""Typed records shared across the app (replaces loose dicts).

from_dict() is tolerant: unknown keys are dropped, bad enum values fall
back to defaults, so files written by older versions still load.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, TypeVar

from walkie.policy import DEFAULT_DURATION, DEFAULT_TIME

E = TypeVar("E", bound=Enum)

FINGERPRINT_UNAVAILABLE = "unavailable"


class LocationType(str, Enum):
    SHADE = "shade"
    SUN = "sun"
    ANY = "any"


class Intensity(str, Enum):
    RELAXED = "relaxed"
    MODERATE = "moderate"
    BRISK = "brisk"


def _enum(enum_cls: type[E], value: Any, default: E) -> E:
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def _str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class UserPlan:
    preferred_time: str = DEFAULT_TIME
    duration_minutes: int = DEFAULT_DURATION
    location_type: LocationType = LocationType.SHADE
    intensity: Intensity = Intensity.MODERATE
    area: str = ""
    quote: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserPlan:
        return cls(
            preferred_time=_str(data.get("preferred_time"), DEFAULT_TIME),
            duration_minutes=_int(data.get("duration_minutes"), DEFAULT_DURATION),
            location_type=_enum(
                LocationType, data.get("location_type"), LocationType.SHADE
            ),
            intensity=_enum(Intensity, data.get("intensity"), Intensity.MODERATE),
            area=_str(data.get("area")),
            quote=_str(data.get("quote")),
            created_at=_str(data.get("created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferred_time": self.preferred_time,
            "duration_minutes": self.duration_minutes,
            "location_type": self.location_type.value,
            "intensity": self.intensity.value,
            "area": self.area,
            "quote": self.quote,
            "created_at": self.created_at,
        }

    def fingerprint(self) -> str:
        """Stable id of the walk *schedule* (not quote/timestamp).

        Derived records (proposal, plan, today's approval) store this so a
        wizard change to any schedule input invalidates them and they get
        regenerated on the next run — no manual --force-new needed.
        """
        return "|".join(
            (
                self.preferred_time,
                str(self.duration_minutes),
                self.location_type.value,
                self.intensity.value,
                self.area,
            )
        )


@dataclass(frozen=True)
class Weather:
    fetched_at: int = 0
    timezone: str = "UTC"
    summary: str = ""
    weather_code: int = -1
    temperature_2m: float | None = None
    temperature_2m_min: float | None = None
    temperature_2m_max: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability_max: int = 0
    wind_speed_10m: float | None = None
    cloud_cover: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Weather:
        return cls(
            fetched_at=_int(data.get("fetched_at"), 0),
            timezone=_str(data.get("timezone"), "UTC"),
            summary=_str(data.get("summary")),
            weather_code=_int(data.get("weather_code"), -1),
            temperature_2m=_opt_float(data.get("temperature_2m")),
            temperature_2m_min=_opt_float(data.get("temperature_2m_min")),
            temperature_2m_max=_opt_float(data.get("temperature_2m_max")),
            precipitation_mm=_opt_float(data.get("precipitation_mm")),
            precipitation_probability_max=_int(
                data.get("precipitation_probability_max"), 0
            ),
            wind_speed_10m=_opt_float(data.get("wind_speed_10m")),
            cloud_cover=_opt_float(data.get("cloud_cover")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class Daylight:
    for_date: str = ""
    sunrise: str | None = None  # "HH:MM" local
    sunset: str | None = None
    daylight_minutes: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Daylight:
        return cls(
            for_date=_str(data.get("for_date")),
            sunrise=_opt_str(data.get("sunrise")),
            sunset=_opt_str(data.get("sunset")),
            daylight_minutes=_int(data.get("daylight_minutes"), 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True)
class Proposal:
    suggested_time: str = ""
    duration_minutes: int = DEFAULT_DURATION
    location_type: LocationType = LocationType.SHADE
    intensity: Intensity = Intensity.MODERATE
    area: str = ""
    weather_summary: str = ""
    weather_fingerprint: str = FINGERPRINT_UNAVAILABLE
    reason: str = ""
    route_notes: str = ""
    created_at: str = ""
    approve_by: str = ""
    for_date: str = ""  # the day the proposal targets (YYYY-MM-DD)
    base_fingerprint: str = ""  # UserPlan.fingerprint() it was built from

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Proposal:
        return cls(
            suggested_time=_str(data.get("suggested_time")),
            duration_minutes=_int(data.get("duration_minutes"), DEFAULT_DURATION),
            location_type=_enum(
                LocationType, data.get("location_type"), LocationType.SHADE
            ),
            intensity=_enum(Intensity, data.get("intensity"), Intensity.MODERATE),
            area=_str(data.get("area")),
            weather_summary=_str(data.get("weather_summary")),
            weather_fingerprint=_str(
                data.get("weather_fingerprint"), FINGERPRINT_UNAVAILABLE
            ),
            reason=_str(data.get("reason")),
            route_notes=_str(data.get("route_notes")),
            created_at=_str(data.get("created_at")),
            approve_by=_str(data.get("approve_by")),
            for_date=_str(data.get("for_date")),
            base_fingerprint=_str(data.get("base_fingerprint")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["location_type"] = self.location_type.value
        data["intensity"] = self.intensity.value
        return data

    def approve(self, approved_at: str, approved_by: str) -> TodayPlan:
        # Proposal fields only: `self` may already be a TodayPlan, whose
        # approval fields must not be passed in twice.
        base = {f.name: getattr(self, f.name) for f in fields(Proposal)}
        return TodayPlan(**base, approved_at=approved_at, approved_by=approved_by)


@dataclass(frozen=True)
class TodayPlan(Proposal):
    approved_at: str = ""
    approved_by: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodayPlan:
        base = Proposal.from_dict(data)
        return cls(
            **{f.name: getattr(base, f.name) for f in fields(Proposal)},
            approved_at=_str(data.get("approved_at")),
            approved_by=_str(data.get("approved_by")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["approved_at"] = self.approved_at
        data["approved_by"] = self.approved_by
        return data


@dataclass(frozen=True)
class Plan:
    """Output of the AI decision engine (output/plans/plan.json)."""

    SOURCE_LLM = "llm"
    SOURCE_FALLBACK = "fallback"

    for_date: str = ""
    window_start: str = ""  # "HH:MM"
    window_end: str = ""  # computed: window_start + duration
    duration_minutes: int = DEFAULT_DURATION
    location_type: LocationType = LocationType.SHADE
    intensity: Intensity = Intensity.MODERATE
    area: str = ""
    sunrise: str | None = None
    sunset: str | None = None
    daylight_minutes: int = 0
    weather_summary: str = ""
    weather_fingerprint: str = FINGERPRINT_UNAVAILABLE
    reason: str = ""
    route_notes: str = ""
    source: str = SOURCE_FALLBACK  # llm | fallback
    created_at: str = ""
    base_fingerprint: str = ""  # UserPlan.fingerprint() it was built from

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        return cls(
            for_date=_str(data.get("for_date")),
            window_start=_str(data.get("window_start")),
            window_end=_str(data.get("window_end")),
            duration_minutes=_int(data.get("duration_minutes"), DEFAULT_DURATION),
            location_type=_enum(
                LocationType, data.get("location_type"), LocationType.SHADE
            ),
            intensity=_enum(Intensity, data.get("intensity"), Intensity.MODERATE),
            area=_str(data.get("area")),
            sunrise=_opt_str(data.get("sunrise")),
            sunset=_opt_str(data.get("sunset")),
            daylight_minutes=_int(data.get("daylight_minutes"), 0),
            weather_summary=_str(data.get("weather_summary")),
            weather_fingerprint=_str(
                data.get("weather_fingerprint"), FINGERPRINT_UNAVAILABLE
            ),
            reason=_str(data.get("reason")),
            route_notes=_str(data.get("route_notes")),
            source=_str(data.get("source"), cls.SOURCE_FALLBACK),
            created_at=_str(data.get("created_at")),
            base_fingerprint=_str(data.get("base_fingerprint")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["location_type"] = self.location_type.value
        data["intensity"] = self.intensity.value
        return data
