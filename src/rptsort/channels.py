"""Channel records: parsing, filtering, sorting, grouping and naming."""

from __future__ import annotations

import bisect
import re
from collections import Counter
from dataclasses import dataclass

from .geo import Geocoder, haversine_km, state_code

SORTS = ("distance", "band", "town", "rings")

BANDS = (
    (28.0, 29.7, "10M"),
    (50.0, 54.0, "6M"),
    (144.0, 148.0, "2M"),
    (219.0, 225.0, "1.25M"),
    (420.0, 450.0, "70CM"),
    (902.0, 928.0, "33CM"),
    (1240.0, 1300.0, "23CM"),
)
BAND_NAMES = tuple(b[2] for b in BANDS)

NAME_FORMATS = {
    "keep": None,
    "call": ("call",),
    "call-town": ("call", "town"),
    "call-band": ("call", "band"),
    "call-freq": ("call", "freq"),
    "town": ("town",),
    "town-band": ("town", "band"),
    "town-freq": ("town", "freq"),
}

# Used only when a generated name is too long for the radio.
ABBREVIATIONS = {
    "springs": "Spg", "spring": "Spg", "mountain": "Mtn", "mount": "Mt",
    "saint": "St", "fort": "Ft", "city": "Cty", "north": "N", "south": "S",
    "east": "E", "west": "W", "lake": "Lk", "heights": "Hts", "village": "Vlg",
    "junction": "Jct", "center": "Ctr", "island": "Isl", "valley": "Vly",
    "park": "Pk", "grove": "Grv", "point": "Pt", "beach": "Bch", "creek": "Crk",
    "falls": "Fls", "hills": "Hls", "ridge": "Rdg", "station": "Sta",
}

CALLSIGN_RE = re.compile(r"\b([A-Z]{1,2}[0-9][A-Z]{1,4})\b")
USE_RE = re.compile(r"\bUse:\s*([A-Za-z]+)")
CLOSED_USES = {"CLOSED", "PRIVATE"}


@dataclass
class Chan:
    row: dict
    freq: float
    call: str = ""
    town: str = ""
    state: str = ""
    county: str = ""
    use: str = ""
    src: str | None = None  # override | town | county | None (not located)
    dist: float | None = None  # km from the center


def band_label(freq: float) -> str:
    for lo, hi, label in BANDS:
        if lo <= freq <= hi:
            return label
    return ""


def freq_label(freq: float) -> str:
    """147.210000 -> '147.21', 146.000 -> '146.0'."""
    text = f"{freq:.4f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def parse_location(comment: str) -> tuple[str, str, str]:
    """Pull (town, state, county) out of a RepeaterBook comment, or blanks."""
    head = (comment or "").split("|", 1)[0]
    parts = [p.strip() for p in head.split(",")]
    if len(parts) >= 2 and parts[0] and state_code(parts[1]):
        return parts[0], parts[1], parts[2] if len(parts) >= 3 else ""
    return "", "", ""


def is_repeater_row(row: dict) -> bool:
    return bool(parse_location(row.get("Comment", ""))[0])


def make_chan(row: dict, geo: Geocoder, center: tuple[float, float]) -> Chan:
    try:
        freq = float(row.get("Frequency") or 0)
    except ValueError:
        freq = 0.0
    town, state, county = parse_location(row.get("Comment", ""))
    call = CALLSIGN_RE.search((row.get("Name") or "").upper())
    use = USE_RE.search(row.get("Comment") or "")
    chan = Chan(row=row, freq=freq, call=call.group(1) if call else "",
                town=town, state=state, county=county,
                use=use.group(1).upper() if use else "")
    hit = geo.locate(town, state, county) if town else None
    if hit:
        lat, lon, chan.src = hit
        chan.dist = haversine_km(center[0], center[1], lat, lon)
    return chan


def dup_key(c: Chan) -> tuple:
    """Same callsign, frequency, offset and tones = same repeater."""
    r = c.row

    def num(v):
        try:
            return round(float(v or 0), 5)
        except ValueError:
            return v

    return (c.call or (r.get("Name") or "").strip().upper(), round(c.freq, 5),
            r.get("Duplex", ""), num(r.get("Offset")), r.get("Tone", ""),
            num(r.get("rToneFreq")), num(r.get("cToneFreq")), r.get("DtcsCode", ""))


def drop_duplicates(chans: list[Chan]) -> tuple[list[Chan], int]:
    seen, out = set(), []
    for c in chans:
        k = dup_key(c)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out, len(chans) - len(out)


def apply_filters(chans: list[Chan], bands: list[str], open_only: bool,
                  max_km: float) -> tuple[list[Chan], Counter]:
    kept, dropped = [], Counter()
    for c in chans:
        if bands and band_label(c.freq) not in bands:
            dropped["band"] += 1
        elif open_only and c.use in CLOSED_USES:
            dropped["closed/private"] += 1
        elif max_km and c.dist is not None and c.dist > max_km:
            dropped["too far"] += 1
        else:
            kept.append(c)
    return kept, dropped


def sort_chans(chans: list[Chan], how: str, rings_km: list[float]) -> list[Chan]:
    far = float("inf")

    def dist(c):
        return c.dist if c.dist is not None else far

    def ring(c):
        return bisect.bisect_right(rings_km, c.dist) if c.dist is not None else len(rings_km) + 1

    keys = {
        "distance": lambda c: (dist(c), c.freq),
        "band": lambda c: (c.freq, dist(c)),  # frequency order == band, then frequency
        "town": lambda c: (c.town.lower() or "￿", c.state.lower(), c.freq),
        "rings": lambda c: (ring(c), c.freq),
    }
    return sorted(chans, key=keys[how])


def group_by_call(chans: list[Chan]) -> list[Chan]:
    """Pull same-callsign channels together at the position of the first one."""
    groups: dict[object, list[Chan]] = {}
    for c in chans:
        groups.setdefault(c.call or id(c), []).append(c)
    return [c for g in groups.values() for c in g]


def abbreviate(town: str) -> str:
    return " ".join(ABBREVIATIONS.get(w.lower(), w) for w in town.split())


def make_name(c: Chan, pieces: tuple[str, ...], max_len: int, upper: bool):
    """Return (name, was_cut), or None when a needed piece (call/town) is missing."""
    values = {"call": c.call, "town": c.town, "band": band_label(c.freq),
              "freq": freq_label(c.freq)}
    if any(not values[p] for p in pieces):
        return None
    parts = [values[p] for p in pieces]
    ti = pieces.index("town") if "town" in pieces else None

    def join():
        return " ".join(x for x in parts if x)

    cut = False
    name = join()
    if len(name) > max_len and ti is not None:
        parts[ti] = abbreviate(parts[ti])
        name = join()
    if len(name) > max_len and ti is not None:
        others = " ".join(x for i, x in enumerate(parts) if i != ti and x)
        budget = max_len - len(others) - (1 if others else 0)
        parts[ti] = parts[ti][: max(budget, 0)].rstrip()
        name = join()
        cut = True
    if len(name) > max_len:
        name = name[:max_len].rstrip()
        cut = True
    return (name.upper() if upper else name), cut


def dedupe_pieces(pieces: tuple[str, ...]) -> tuple[str, ...]:
    """call-band -> call-freq, town -> town-freq, call-town -> call-town-freq."""
    p = tuple("freq" if x == "band" else x for x in pieces)
    return p if "freq" in p else p + ("freq",)


def assign_names(chans: list[Chan], fmt: str, max_len: int, upper: bool,
                 dedupe: bool) -> dict[str, list[Chan]]:
    """Rename channels in place. Returns lists of channels for reporting."""
    report: dict[str, list[Chan]] = {"cut": [], "unnamed": [], "deduped": []}
    if fmt == "keep":
        return report
    pieces = NAME_FORMATS[fmt]
    cut: dict[int, bool] = {}
    for c in chans:
        res = make_name(c, pieces, max_len, upper)
        if res is None:
            report["unnamed"].append(c)
            continue
        c.row["Name"], cut[id(c)] = res

    if dedupe:
        counts = Counter(c.row["Name"] for c in chans)
        alt = dedupe_pieces(pieces)
        for c in chans:
            if id(c) in cut and counts[c.row["Name"]] > 1:
                res = make_name(c, alt, max_len, upper)
                if res:
                    c.row["Name"], cut[id(c)] = res
                    report["deduped"].append(c)
        # Last resort for anything still shared: number the repeats.
        counts = Counter(c.row["Name"] for c in chans)
        seen: Counter = Counter()
        for c in chans:
            name = c.row["Name"]
            if id(c) in cut and counts[name] > 1:
                seen[name] += 1
                if seen[name] > 1:
                    tag = f" {seen[name]}"
                    c.row["Name"] = name[: max_len - len(tag)].rstrip() + tag

    report["cut"] = [c for c in chans if cut.get(id(c))]
    return report


def tone_text(row: dict) -> str:
    mode = row.get("Tone", "")
    if mode == "Tone":
        return f"T {row.get('rToneFreq', '')}"
    if mode == "TSQL":
        return f"TSQL {row.get('cToneFreq', '')}"
    if mode == "DTCS":
        return f"DCS {row.get('DtcsCode', '')}"
    if mode == "Cross":
        if row.get("CrossMode") == "Tone->Tone":  # TX tone / RX tone
            return f"T {row.get('rToneFreq', '')}/{row.get('cToneFreq', '')}"
        return f"X {row.get('CrossMode', '')}"
    return ""


def offset_text(row: dict) -> str:
    duplex = row.get("Duplex", "")
    if duplex in ("+", "-"):
        try:
            return f"{duplex}{float(row.get('Offset') or 0):g}"
        except ValueError:
            return duplex
    return duplex
