"""Group reordered channels into radio zones and format them for pasting into CHIRP."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from .channels import Chan

ZONE_MODES = ("none", "local+state", "state", "rings")
DEFAULT_LOCAL_KM = 80.0


@dataclass
class Zone:
    name: str
    channels: list[int] = field(default_factory=list)
    bank: int = 0  # fixed-bank radios: the bank this zone fills (0 = not placed)


def _ring_labels(rings: list[float], unit: str) -> list[str]:
    edges = [0.0, *rings]
    labels = [f"{lo:g}-{hi:g} {unit}" for lo, hi in zip(edges, edges[1:])]
    return labels + [f"{edges[-1]:g}+ {unit}"]


def build_zones(chans: list[Chan], mode: str, *, local_km: float, rings: list[float],
                rings_km: list[float], unit: str, zone_max: int, name_len: int,
                kept_locations: list[int], keep_zone: str) -> list[Zone]:
    """Return zones in display order. `chans` must already be in final order and numbered.

    local+state: one "Local" zone (everything within local_km, any state), then
                 one zone per state for the rest.
    state:       one zone per state.
    rings:       one zone per distance ring.
    Channels with no usable location go in "Other". Zones keep channel order,
    are ordered by their first channel, and are split when larger than zone_max.
    """
    if mode == "none":
        return []
    labels = _ring_labels(rings, unit)
    order: dict[str, tuple] = {}
    members: dict[str, list[int]] = {}
    for i, c in enumerate(chans):
        if mode == "local+state" and c.dist is not None and c.dist <= local_km:
            key, rank = "Local", 0
        elif mode == "rings":
            if c.dist is None:
                key, rank = "Other", len(labels) + 1
            else:
                ring = bisect.bisect_right(rings_km, c.dist)
                key, rank = labels[ring], ring
        elif c.state:
            key, rank = c.state, 1
        else:
            key, rank = "Other", 2
        order.setdefault(key, (rank, i))
        members.setdefault(key, []).append(int(c.row["Location"]))

    zones: list[Zone] = []
    for key in sorted(members, key=lambda k: order[k]):
        locs = members[key]
        if len(locs) <= zone_max:
            zones.append(Zone(key[:name_len], locs))
            continue
        for n, start in enumerate(range(0, len(locs), zone_max), 1):
            suffix = f" {n}"
            zones.append(Zone(key[: name_len - len(suffix)] + suffix, locs[start:start + zone_max]))

    if keep_zone and kept_locations:
        locs = sorted(kept_locations)
        for n, start in enumerate(range(0, len(locs), zone_max), 1):
            suffix = f" {n}" if len(locs) > zone_max else ""
            zones.append(Zone(keep_zone[: name_len - len(suffix)] + suffix,
                              locs[start:start + zone_max]))
    return zones


def place_in_banks(zones: list[Zone], block: int, first_bank: int = 1) -> dict[int, int]:
    """Fixed-bank radios: give each zone its own bank of `block` channels.

    Bank n holds channels (n-1)*block+1 .. n*block. Zones fill banks in order,
    starting at first_bank, each from the start of its bank. Updates the zones
    and returns {old location: new location}. Zones must fit in one bank
    (build them with zone_max=block).
    """
    moves: dict[int, int] = {}
    for n, z in enumerate(zones):
        z.bank = first_bank + n
        start = (z.bank - 1) * block + 1
        new = list(range(start, start + len(z.channels)))
        moves.update(zip(z.channels, new))
        z.channels = new
    return moves


def format_zones(zones: list[Zone], block: int = 0) -> str:
    """Text for CHIRP: zone lists to paste in, or (fixed banks) what each bank holds."""
    if block:
        lines = [
            f"Banks: this radio has fixed banks of {block} channels; a channel's number "
            "picks its bank.",
            "Name the banks to match (WebCHIRP: Radio Settings > Bank names).",
            "",
        ]
        for z in zones:
            k, lo, hi = len(z.channels), z.channels[0], z.channels[-1]
            span = f"{lo}" if lo == hi else f"{lo}-{hi}"
            lines.append(f"Bank {z.bank}: {z.name}  ({k} channel{'' if k == 1 else 's'}: {span})")
        return "\n".join(lines) + "\n"
    lines = [
        "Zones: paste each list into CHIRP (WebCHIRP: Radio Settings > Zones).",
        f"Zone order: {', '.join(str(n) for n in range(1, len(zones) + 1))}",
        "",
    ]
    for n, z in enumerate(zones, 1):
        lines.append(f"Zone {n}: {z.name}  ({len(z.channels)} channels)")
        lines.append(", ".join(str(x) for x in z.channels))
        lines.append("")
    return "\n".join(lines)
