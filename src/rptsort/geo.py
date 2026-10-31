"""Town and county coordinates from the US Census Gazetteer, plus distance math."""

from __future__ import annotations

import csv
import io
import math
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import RptsortError

GAZ_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
GAZ_PLACES = "2024_Gaz_place_national.zip"
GAZ_COUNTIES = "2024_Gaz_counties_national.zip"

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "puerto rico": "PR", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
STATE_CODES = set(STATES.values())

LATLON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
PLACE_SUFFIX_RE = re.compile(
    r"\s+(?:(?:unified|consolidated|metropolitan|metro) government \(balance\)"
    r"|\(balance\)|city and borough|zona urbana|comunidad|city|town|village|cdp"
    r"|borough|township|municipality|corporation)$",
    re.IGNORECASE,
)
COUNTY_SUFFIX_RE = re.compile(
    r"\s+(?:county|parish|borough|census area|city and borough|municipality|municipio)$",
    re.IGNORECASE,
)


def default_cache_dir() -> Path:
    if os.environ.get("RPTSORT_CACHE"):
        return Path(os.environ["RPTSORT_CACHE"])
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "rptsort"


def norm(text: str) -> str:
    """Normalize a place name for matching: case, punctuation, St/Mt/Ft."""
    s = text.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[.'’`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    swap = {"saint": "st", "sainte": "ste", "mount": "mt", "fort": "ft"}
    return " ".join(swap.get(w, w) for w in s.split())


def state_code(state: str) -> str | None:
    s = state.strip()
    if s.upper() in STATE_CODES:
        return s.upper()
    return STATES.get(s.lower())


def parse_latlon(spec: str) -> tuple[float, float] | None:
    m = LATLON_RE.match(spec)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise RptsortError(f"{spec!r} is not a valid lat,lon")
    return lat, lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_gazetteer(cache_dir: Path, filename: str) -> Path:
    path = cache_dir / filename
    if path.exists():
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = GAZ_URL + filename
    print(f"Downloading {url} (one time, cached in {cache_dir}) ...", file=sys.stderr)
    tmp = path.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise RptsortError(f"could not download {url}: {exc}") from exc
    tmp.rename(path)
    return path


def read_gazetteer(path: Path):
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if n.endswith(".txt"))
        text = zf.read(member).decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = [h.strip() for h in next(reader)]
    for row in reader:
        yield dict(zip(header, (c.strip() for c in row)))


class Geocoder:
    """Look up "Town, State" (falling back to county) in the Census Gazetteer."""

    def __init__(self, cache_dir: Path | None = None, overrides: dict | None = None):
        cache_dir = cache_dir or default_cache_dir()
        self.overrides: dict[tuple[str, str], tuple[float, float]] = {}
        for key, val in (overrides or {}).items():
            parts = [p.strip() for p in key.split(",")]
            st = state_code(parts[1]) if len(parts) >= 2 else None
            ok = isinstance(val, list) and len(val) == 2 and all(
                isinstance(v, (int, float)) for v in val)
            if not st or not ok:
                raise RptsortError(f'[coords] entry {key!r} must look like "Town, ST" = [lat, lon]')
            self.overrides[(st, norm(parts[0]))] = (float(val[0]), float(val[1]))

        # (state, normalized name) -> (lat, lon, priority); lower priority wins
        self.places: dict[tuple[str, str], tuple[float, float, int]] = {}
        for row in read_gazetteer(fetch_gazetteer(cache_dir, GAZ_PLACES)):
            lat, lon = float(row["INTPTLAT"]), float(row["INTPTLONG"])
            prio = 0 if row.get("FUNCSTAT") == "A" else 1  # incorporated beats CDP
            stripped = PLACE_SUFFIX_RE.sub("", row["NAME"])
            for key, p in ((norm(stripped), prio), (norm(row["NAME"]), prio + 2)):
                k = (row["USPS"], key)
                if k not in self.places or p < self.places[k][2]:
                    self.places[k] = (lat, lon, p)

        self.counties: dict[tuple[str, str], tuple[float, float]] = {}
        for row in read_gazetteer(fetch_gazetteer(cache_dir, GAZ_COUNTIES)):
            k = (row["USPS"], norm(COUNTY_SUFFIX_RE.sub("", row["NAME"])))
            self.counties.setdefault(k, (float(row["INTPTLAT"]), float(row["INTPTLONG"])))

    def locate(self, town: str, state: str, county: str = ""):
        """Return (lat, lon, source) or None. source: override | town | county."""
        st = state_code(state)
        if not st:
            return None
        t = norm(town)
        if (st, t) in self.overrides:
            return (*self.overrides[(st, t)], "override")
        if (st, t) in self.places:
            lat, lon, _ = self.places[(st, t)]
            return lat, lon, "town"
        if county:
            c = norm(COUNTY_SUFFIX_RE.sub("", county))
            if (st, c) in self.counties:
                return (*self.counties[(st, c)], "county")
        return None

    def locate_spec(self, spec: str) -> tuple[float, float]:
        """Resolve 'lat,lon' or 'Town, ST' to coordinates."""
        point = parse_latlon(spec)
        if point:
            return point
        parts = [p.strip() for p in spec.split(",")]
        hit = None
        if len(parts) >= 2:
            hit = self.locate(parts[0], parts[1], parts[2] if len(parts) > 2 else "")
        if not hit:
            raise RptsortError(f"can't find {spec!r}; use 'Town, ST' or 'lat,lon'")
        return hit[0], hit[1]
