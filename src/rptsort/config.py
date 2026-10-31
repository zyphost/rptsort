"""Settings: defaults, config-file lookup, presets and validation."""

from __future__ import annotations

import os
import tomllib
from importlib import resources
from pathlib import Path
from string import Template

from . import RptsortError
from .channels import BAND_NAMES, NAME_FORMATS, SORTS

MILE_KM = 1.609344

DEFAULTS = {
    "keep": 0,
    "sort": "distance",
    "rings": [30, 80],
    "center": None,
    "units": "km",
    "name": "keep",
    "name_len": 16,
    "upper": True,
    "dedupe": False,
    "group_calls": False,
    "skip_beyond": 0,
    "max_distance": 0,
    "bands": [],
    "open_only": False,
    "limit": 0,
}

_NUMBER = (int, float)
TYPES = {
    "keep": int, "sort": str, "rings": list, "center": str, "units": str,
    "name": str, "name_len": int, "upper": bool, "dedupe": bool,
    "group_calls": bool, "skip_beyond": _NUMBER, "max_distance": _NUMBER,
    "bands": list, "open_only": bool, "limit": int,
}


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "rptsort" / "config.toml"


def config_candidates() -> list[Path]:
    return [Path.cwd() / "rptsort.toml", user_config_path()]


def load_config(explicit: Path | None) -> tuple[Path | None, dict]:
    """Return (path, data) for the first config found, or (None, {})."""
    if explicit:
        if not explicit.exists():
            raise RptsortError(f"config file not found: {explicit}")
        candidates = [explicit]
    else:
        candidates = [p for p in config_candidates() if p.exists()]
    for path in candidates:
        with open(path, "rb") as fh:
            try:
                return path, tomllib.load(fh)
            except tomllib.TOMLDecodeError as exc:
                raise RptsortError(f"{path}: {exc}") from exc
    return None, {}


def _check_type(key: str, value, where: str) -> None:
    expected = TYPES[key]
    if value is None and key == "center":
        return
    bad_bool = isinstance(value, bool) and expected is not bool
    if bad_bool or not isinstance(value, expected):
        raise RptsortError(f"{where}: {key} has the wrong type ({value!r})")


def check_table(table: dict, where: str) -> dict:
    if not isinstance(table, dict):
        raise RptsortError(f"{where} must be a table of settings")
    unknown = set(table) - set(DEFAULTS)
    if unknown:
        raise RptsortError(f"{where}: unknown setting(s) {', '.join(sorted(unknown))}; "
                           f"valid: {', '.join(DEFAULTS)}")
    for key, value in table.items():
        _check_type(key, value, where)
    return table


def resolve_settings(cfg: dict, preset: str | None, overrides: dict) -> dict:
    """Merge built-in defaults < [defaults] < [presets.NAME] < flags, then validate."""
    settings = dict(DEFAULTS)
    settings.update(check_table(cfg.get("defaults", {}), "[defaults]"))
    if preset:
        presets = cfg.get("presets", {})
        if preset not in presets:
            raise RptsortError(f"unknown preset {preset!r}; "
                               f"available: {', '.join(presets) or '(none)'}")
        settings.update(check_table(presets[preset], f"[presets.{preset}]"))
    settings.update({k: v for k, v in overrides.items() if v is not None})

    if settings["sort"] not in SORTS:
        raise RptsortError(f"sort must be one of: {', '.join(SORTS)}")
    if settings["name"] not in NAME_FORMATS:
        raise RptsortError(f"name must be one of: {', '.join(NAME_FORMATS)}")
    if settings["units"] not in ("km", "mi"):
        raise RptsortError('units must be "km" or "mi"')
    for key in ("keep", "name_len", "limit", "skip_beyond", "max_distance"):
        if settings[key] < 0:
            raise RptsortError(f"{key} can't be negative")
    if settings["name_len"] < 1:
        raise RptsortError("name_len must be at least 1")
    try:
        settings["rings"] = sorted(float(x) for x in settings["rings"])
    except (TypeError, ValueError) as exc:
        raise RptsortError("rings must be a list of distances, e.g. [30, 80]") from exc
    bands = [str(b).upper() for b in settings["bands"]]
    bad = [b for b in bands if b not in BAND_NAMES]
    if bad:
        raise RptsortError(f"unknown band(s) {', '.join(bad)}; valid: {', '.join(BAND_NAMES)}")
    settings["bands"] = bands

    # Distances in the user's units -> km for the math.
    factor = MILE_KM if settings["units"] == "mi" else 1.0
    settings["unit_factor"] = factor
    settings["rings_km"] = [x * factor for x in settings["rings"]]
    settings["skip_beyond_km"] = float(settings["skip_beyond"]) * factor
    settings["max_distance_km"] = float(settings["max_distance"]) * factor
    return settings


def home_from(cfg: dict) -> tuple[float, float] | None:
    home = cfg.get("home", {})
    if "lat" in home and "lon" in home:
        try:
            return float(home["lat"]), float(home["lon"])
        except (TypeError, ValueError) as exc:
            raise RptsortError("[home] lat and lon must be numbers") from exc
    return None


def render_template(lat: float, lon: float, keep: int, name_len: int, units: str) -> str:
    text = resources.files("rptsort").joinpath("config_template.toml").read_text("utf-8")
    km = units == "km"
    return Template(text).substitute(
        lat=f"{lat:.6f}", lon=f"{lon:.6f}", keep=keep, name_len=name_len, units=units,
        rings="[30, 80]" if km else "[20, 50]",
        mobile_skip=80 if km else 50,
        trip_skip=60 if km else 40,
    )
