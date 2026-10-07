"""Detect your location and download the matching Geofabrik OSM extract.

One-time setup step: finds the most specific .pbf extract Geofabrik offers
for where you are (sub-region like a state when available, else country),
downloads it into data/osm/, and writes region + coordinates + timezone
into config/settings.yaml.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from walkie import config
from walkie.log import get_logger

log = get_logger("region")

PBF_DIR = config.DATA_DIR / "osm"
GEOFABRIK = "https://download.geofabrik.de"
UA = {"User-Agent": "walkie-setup/0.1 (local OSM region fetch)"}

CONTINENT_FALLBACK = [
    "africa",
    "asia",
    "europe",
    "north-america",
    "south-america",
    "oceania",
]

# one source: (url, payload parser) — parser returns the same five fields
LocSource = tuple[str, Callable[[dict[str, Any]], tuple[Any, Any, Any, str, str]]]


class RegionError(Exception):
    """Setup problem; the message is user-facing."""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def detect_location() -> tuple[float, float, str, str, str]:
    """Return (lat, lon, country_name, country_code, timezone) from IP."""
    sources: tuple[LocSource, ...] = (
        ("https://ipapi.co/json/", lambda d: (
            d["latitude"], d["longitude"], d["country_name"],
            d.get("country_code", ""), d.get("timezone", "UTC"))),
        ("https://ipwho.is/", lambda d: (
            d["latitude"], d["longitude"], d["country"],
            d.get("country_code", ""), d.get("timezone", {}).get("id", "UTC"))),
        ("https://ip-api.com/json/", lambda d: (
            d["lat"], d["lon"], d["country"],
            d.get("countryCode", ""), d.get("timezone", "UTC"))),
    )
    for url, parse in sources:
        try:
            r = requests.get(url, headers=UA, timeout=10)
            r.raise_for_status()
            lat, lon, country, code, tz = parse(r.json())
            if lat is not None and lon is not None and country:
                log.info(f"Detected location: {lat}, {lon} ({country}) via {url}")
                return float(lat), float(lon), country, code.lower(), tz
        except Exception as exc:  # noqa: BLE001 - try next source
            log.info(f"  {url} failed: {exc}")
    raise RegionError(
        "could not detect location from IP. "
        "Re-run with --lat/--lon (and optionally --name)."
    )


def geofabrik_continents() -> list[str]:
    """Scrape the Geofabrik index for continent dirs; fall back to known list."""
    try:
        r = requests.get(GEOFABRIK + "/", headers=UA, timeout=15)
        r.raise_for_status()
        found = re.findall(r'href="([a-z]+(?:-[a-z]+)*)/"', r.text)
        keep = [c for c in found if c not in {"about", "license", "static", "files"}]
        if keep:
            return list(dict.fromkeys(keep))
    except Exception as exc:  # noqa: BLE001
        log.info(f"  index scrape failed ({exc}); using built-in continent list")
    return CONTINENT_FALLBACK


def reverse_region(lat: float, lon: float) -> str | None:
    """Best-effort sub-region (state/province) for more specific extracts."""
    try:
        params: dict[str, str | float] = {
            "format": "jsonv2",
            "lat": lat,
            "lon": lon,
            "zoom": 5,
        }
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params=params,
            headers=UA,
            timeout=10,
        )
        r.raise_for_status()
        addr = r.json().get("address", {})
        region = (
            addr.get("state") or addr.get("region")
            or addr.get("province") or addr.get("state_district")
        )
        if isinstance(region, str) and region:
            log.info(f"Reverse geocode sub-region: {region}")
            return region
        return None
    except Exception as exc:  # noqa: BLE001
        log.info(f"  reverse geocode failed: {exc}")
        return None


def url_exists(url: str) -> bool:
    try:
        r = requests.head(url, headers=UA, timeout=10, allow_redirects=True)
        if r.status_code == 200:
            return True
        # some mirrors reject HEAD
        r = requests.get(url, headers={**UA, "Range": "bytes=0-0"}, timeout=10)
        return r.status_code in (200, 206)
    except Exception:  # noqa: BLE001
        return False


def _extract_candidates(
    continents: list[str],
    country_slugs: list[str],
    region_slug: str,
    subregion_name: str | None,
    country_name: str,
) -> list[tuple[str, str]]:
    """Build (url, display_name) probes, most specific extracts first.

    Sub-region files live under continent/<country>/<region>/, country files
    under continent/<country>/.
    """
    candidates: list[tuple[str, str]] = []
    if region_slug:
        candidates += [
            (f"{GEOFABRIK}/{continent}/{country_slug}/{region_slug}-latest.osm.pbf",
             subregion_name or region_slug)
            for continent in continents
            for country_slug in country_slugs
        ]
    candidates += [
        (f"{GEOFABRIK}/{continent}/{country_slug}-latest.osm.pbf", country_name)
        for continent in continents
        for country_slug in country_slugs
    ]
    return candidates


def find_extract(
    country_name: str,
    country_code: str,
    subregion_name: str | None,
    continents: list[str],
) -> tuple[str, str]:
    """Probe Geofabrik for the most specific extract. Returns (url, name)."""
    country_slugs = list(dict.fromkeys(
        slug for slug in (slugify(country_name), country_code) if slug
    ))
    region_slug = slugify(subregion_name) if subregion_name else ""

    candidates = _extract_candidates(
        continents, country_slugs, region_slug, subregion_name, country_name
    )
    for extract_url, display_name in candidates:
        if url_exists(extract_url):
            log.info(f"Found extract: {extract_url}")
            return extract_url, display_name

    raise RegionError(
        f"no Geofabrik extract found for {country_name!r} / "
        f"{subregion_name!r}. Check {GEOFABRIK} manually and re-run with "
        "--name, or use --dry-run to debug."
    )


def download(url: str, dest: Path) -> None:
    """Fetch `url` into `dest`; network failures surface as RegionError."""
    log.info(f"Downloading {url} -> {dest}")
    try:
        r = requests.get(url, headers=UA, stream=True, timeout=60)
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        if total > 700 * 1024 * 1024:
            log.info(f"  warning: {total / 1e6:.0f} MB is large; consider a "
                     "sub-region if your country is split on Geofabrik")
        done = 0
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:.0f} / {total / 1e6:.0f} MB",
                          end="", file=sys.stderr)
    except requests.RequestException as exc:
        raise RegionError(f"download of {url} failed: {exc}") from exc
    log.info(f"\nDownloaded {done / 1e6:.0f} MB")


def _format_coordinate(value: float) -> str:
    """Render a float coordinate compactly (6.31625, not 6.316250)."""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _scalar_needs_quotes(value: object) -> bool:
    """True when a string scalar must be quoted to survive YAML parsing."""
    if not isinstance(value, str):
        return False
    return ":" in value or "#" in value or value != value.strip()


def _replace_setting_line(
    line: str,
    section: str | None,
    replacements: dict[tuple[str, str], str],
) -> str:
    """Rewrite one settings.yaml line if it holds a key awaiting replacement."""
    sub_key = re.match(r"^(\s+)([A-Za-z_][\w-]*):(.*)$", line)
    if not sub_key or not section:
        return line
    key = (section, sub_key.group(2))
    if key not in replacements:
        return line
    value = replacements.pop(key)
    indent, key_name = sub_key.group(1), sub_key.group(2)
    rendered = f'"{value}"' if _scalar_needs_quotes(value) else value
    return f"{indent}{key_name}: {rendered}"


def update_settings(
    pbf_rel: str,
    region_name: str,
    lat: float,
    lon: float,
    tz: str,
    settings_path: Path = config.SETTINGS_PATH,
) -> None:
    """Update known keys in config/settings.yaml, preserving comments."""
    replacements: dict[tuple[str, str], str] = {
        ("region", "name"): region_name,
        ("region", "pbf"): pbf_rel,
        ("location", "lat"): _format_coordinate(lat),
        ("location", "lon"): _format_coordinate(lon),
        ("location", "timezone"): tz,
    }
    section: str | None = None
    out: list[str] = []
    for line in settings_path.read_text().splitlines():
        # the regex only matches unindented lines, so these are section keys
        top_level_key = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if top_level_key:
            section = top_level_key.group(1)
        out.append(_replace_setting_line(line, section, replacements))
    if replacements:
        log.warning(f"keys not found in settings.yaml: {sorted(replacements)}")
    settings_path.write_text("\n".join(out) + "\n")
    log.info(f"Updated {settings_path}")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lat", type=float, help="override latitude")
    parser.add_argument("--lon", type=float, help="override longitude")
    parser.add_argument("--name", help="override country/region name")
    parser.add_argument("--dry-run", action="store_true",
                        help="detect and plan, but do not download or write")


def _resolve_location(
    args: argparse.Namespace,
) -> tuple[float, float, str, str, str]:
    """Return (lat, lon, country_name, country_code, timezone)."""
    if args.lat is not None and args.lon is not None:
        log.info(f"Using manual coordinates: {args.lat}, {args.lon}")
        country_name = args.name or ""
        if not country_name:
            raise RegionError("--lat/--lon require --name as well")
        return args.lat, args.lon, country_name, "", "UTC"
    lat, lon, country_name, country_code, timezone_name = detect_location()
    if args.name:
        country_name = args.name
    return lat, lon, country_name, country_code, timezone_name


def _download_extract(extract_url: str, dest: Path) -> None:
    """Download unless already present; clean up partial files on failure."""
    PBF_DIR.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        log.info(f"Already downloaded: {dest} (delete to re-fetch)")
        return
    partial = dest.with_suffix(dest.suffix + ".part")
    try:
        download(extract_url, partial)
        partial.rename(dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def execute(args: argparse.Namespace) -> None:
    """Run the fetch; raises RegionError with a user-facing message on failure."""
    lat, lon, country_name, country_code, timezone_name = _resolve_location(args)

    continents = geofabrik_continents()
    subregion_name = reverse_region(lat, lon)
    extract_url, region_name = find_extract(
        country_name=country_name,
        country_code=country_code,
        subregion_name=subregion_name,
        continents=continents,
    )

    pbf_filename = extract_url.rsplit("/", 1)[-1]
    dest = PBF_DIR / pbf_filename
    pbf_setting = f"data/osm/{pbf_filename}"

    if args.dry_run:
        log.info(f"dry run: would download {extract_url} -> {dest}")
        log.info(f"dry run: would set region={region_name!r}, lat={lat}, "
                 f"lon={lon}, tz={timezone_name}")
        return

    _download_extract(extract_url, dest)

    if config.SETTINGS_PATH.exists():
        update_settings(pbf_setting, region_name, lat, lon, timezone_name)
    else:
        log.warning(f"{config.SETTINGS_PATH} not found; set region manually")

    log.info("Done. Region setup complete.")
