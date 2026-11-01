"""Command-line interface: `rptsort [PRESET] FILE.csv ...` and `rptsort init`."""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

from . import RptsortError, __version__
from .channels import (
    NAME_FORMATS, SORTS, Chan, apply_filters, assign_names, drop_duplicates,
    group_by_call, is_repeater_row, make_chan, offset_text, sort_chans, tone_text,
)
from .config import (
    home_from, load_config, render_template, resolve_settings, user_config_path,
)
from .geo import Geocoder, default_cache_dir, parse_latlon, state_code
from .zones import ZONE_MODES, build_zones, format_zones

USAGE = """\
rptsort [PRESET] FILE.csv [MORE.csv ...] [options]
       rptsort init [options]"""


def warn(msg: str = "") -> None:
    print(msg, file=sys.stderr)


# ------------------------------------------------------------------ CSV in/out

def read_csv(path: Path) -> tuple[list[str], list[dict], str]:
    """Return (header, rows, newline) for a CHIRP CSV file."""
    if not path.is_file():
        raise RptsortError(f"input file not found: {path}")
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    header = list(reader.fieldnames or [])
    for col in ("Location", "Name", "Frequency"):
        if col not in header:
            raise RptsortError(f"{path.name} doesn't look like a CHIRP CSV (no {col!r} column)")
    rows = list(reader)
    for r in rows:
        try:
            int(r["Location"])
        except (TypeError, ValueError) as exc:
            raise RptsortError(f"{path.name}: every row needs a numeric Location") from exc
    return header, rows, newline


def write_csv(path: Path, header: list[str], rows: list[dict], newline: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator=newline,
                                restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------------ sort command

def build_sort_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rptsort", usage=USAGE,
        description="Reorder, rename and scan-skip repeater channels in CHIRP CSV files. "
                    "Run 'rptsort init' first to create a settings file.",
        epilog="Example: rptsort mobile my-export.csv --dry-run",
    )
    p.add_argument("args", nargs="+", metavar="[PRESET] FILE.csv",
                   help="optional preset from your settings file, then one or more CHIRP "
                        "CSV files (several files are merged)")
    p.add_argument("--version", action="version", version=f"rptsort {__version__}")
    p.add_argument("-c", "--config", type=Path, help="settings file to use")
    p.add_argument("-o", "--output", type=Path, help="output CSV (default FILE-PRESET.csv)")
    p.add_argument("--dry-run", action="store_true", help="show the result, write nothing")
    p.add_argument("-q", "--quiet", action="store_true", help="don't print the channel table")

    g = p.add_argument_group("ordering")
    g.add_argument("--keep", type=int, help="leave channels 1..KEEP untouched")
    g.add_argument("--sort", choices=SORTS)
    g.add_argument("--rings", help="distance boundaries for --sort rings, e.g. 30,80")
    g.add_argument("--from", dest="center", metavar="CENTER",
                   help="sort center: 'Town, ST', 'lat,lon' or 'home'")
    g.add_argument("--group-calls", action=argparse.BooleanOptionalAction, default=None,
                   help="keep same-callsign repeaters together")
    g.add_argument("--units", choices=("km", "mi"))

    g = p.add_argument_group("names")
    g.add_argument("--name", choices=list(NAME_FORMATS), help="channel name format")
    g.add_argument("--name-len", type=int, help="max name length for the radio")
    g.add_argument("--upper", action=argparse.BooleanOptionalAction, default=None,
                   help="uppercase generated names")
    g.add_argument("--dedupe", action=argparse.BooleanOptionalAction, default=None,
                   help="give channels that would share a name a frequency-style name")

    g = p.add_argument_group("filters")
    g.add_argument("--skip-beyond", type=float, metavar="DIST",
                   help="scan-skip channels farther than DIST (0 = leave Skip alone)")
    g.add_argument("--max-distance", type=float, metavar="DIST",
                   help="remove channels farther than DIST (0 = no limit)")
    g.add_argument("--bands", help="keep only these bands, e.g. 2M,70CM")
    g.add_argument("--open-only", action=argparse.BooleanOptionalAction, default=None,
                   help="remove repeaters listed as CLOSED or PRIVATE")
    g.add_argument("--limit", type=int, help="keep at most N reordered channels (0 = no limit)")

    g = p.add_argument_group("zones (printed and saved as FILE-PRESET-zones.txt)")
    g.add_argument("--zones", choices=ZONE_MODES,
                   help="group channels into zones: local+state, state or rings")
    g.add_argument("--zone-local", type=float, metavar="DIST",
                   help="Local zone cutoff for --zones local+state (default: --skip-beyond, else 80 km)")
    g.add_argument("--zone-max", type=int, metavar="N", help="split zones bigger than N (default 60)")
    g.add_argument("--keep-zone", metavar="NAME", help="add a zone with the kept top channels")
    return p


def cli_overrides(a: argparse.Namespace) -> dict:
    out = {k: getattr(a, k) for k in (
        "keep", "sort", "center", "group_calls", "units", "name", "name_len", "upper",
        "dedupe", "skip_beyond", "max_distance", "open_only", "limit",
        "zones", "zone_local", "zone_max", "keep_zone")}
    if a.rings:
        try:
            out["rings"] = [float(x) for x in a.rings.split(",") if x.strip()]
        except ValueError as exc:
            raise RptsortError(f"--rings must be comma-separated numbers, got {a.rings!r}") from exc
    if a.bands is not None:
        out["bands"] = [b.strip() for b in a.bands.split(",") if b.strip()]
    return out


def split_positionals(args: list[str], presets: dict) -> tuple[str | None, list[Path]]:
    first = args[0]
    if first in presets:
        preset, files = first, args[1:]
    elif not first.lower().endswith(".csv") and not Path(first).is_file():
        raise RptsortError(f"{first!r} is not a CSV file or a preset; "
                           f"presets: {', '.join(presets) or '(none)'}")
    else:
        preset, files = None, args
    if not files:
        raise RptsortError("no input CSV file given")
    return preset, [Path(f) for f in files]


def print_table(chans: list[Chan], unit: str, factor: float) -> None:
    name_w = max([4] + [len(c.row.get("Name", "")) for c in chans])
    tone_w = max([4] + [len(tone_text(c.row)) for c in chans])
    print(f"{'Loc':>4}  {'Name':<{name_w}}  {'Freq':>10}  {'Off':>5}  {'Tone':<{tone_w}}"
          f"  {unit:>5}  Skip  Town")
    for c in chans:
        r = c.row
        dist = "?" if c.dist is None else (
            f"{'~' if c.src == 'county' else ''}{c.dist / factor:.0f}")
        town = f"{c.town}, {state_code(c.state)}" if c.town else ""
        print(f"{r['Location']:>4}  {r.get('Name', ''):<{name_w}}  {r.get('Frequency', ''):>10}"
              f"  {offset_text(r):>5}  {tone_text(r):<{tone_w}}  {dist:>5}"
              f"  {r.get('Skip', '') or '':<4}  {town}")
    if any(c.src == "county" for c in chans):
        print("~ = located by county center (town not in Census list)")
    sys.stdout.flush()


def run_sort(argv: list[str]) -> Path | None:
    parser = build_sort_parser()
    a = parser.parse_args(argv)
    cfg_path, cfg = load_config(a.config)
    preset, files = split_positionals(a.args, cfg.get("presets", {}))
    s = resolve_settings(cfg, preset, cli_overrides(a))
    keep = s["keep"]

    # --- read input files
    header, rows, newline = read_csv(files[0])
    kept = [r for r in rows if int(r["Location"]) <= keep]
    movable = [r for r in rows if int(r["Location"]) > keep]
    ignored = {}
    for extra in files[1:]:
        _, extra_rows, _ = read_csv(extra)
        take = [r for r in extra_rows if int(r["Location"]) > keep or is_repeater_row(r)]
        ignored[extra.name] = len(extra_rows) - len(take)
        movable += [{k: r.get(k, "") for k in header} for r in take]
    if not movable:
        raise RptsortError(f"no channels after #{keep} to reorder")

    geo = Geocoder(default_cache_dir(), cfg.get("coords", {}))
    home = home_from(cfg)
    if s["center"] in (None, "", "home"):
        if not home:
            raise RptsortError("no home location: run 'rptsort init', or pass --from 'Town, ST'")
        center, center_label = home, "home"
    else:
        center, center_label = geo.locate_spec(s["center"]), s["center"]
    chans = [make_chan(r, geo, center) for r in movable]

    # --- merge, filter, order, limit
    dup_count = 0
    if len(files) > 1:
        chans, dup_count = drop_duplicates(chans)
    chans, dropped = apply_filters(chans, s["bands"], s["open_only"], s["max_distance_km"])
    chans = sort_chans(chans, s["sort"], s["rings_km"])
    if s["group_calls"]:
        chans = group_by_call(chans)
    over_limit = []
    if s["limit"] and len(chans) > s["limit"]:
        chans, over_limit = chans[: s["limit"]], chans[s["limit"]:]
    if not chans:
        raise RptsortError("every channel was filtered out; loosen the filters")

    # --- rename, scan-skip, renumber
    names = assign_names(chans, s["name"], s["name_len"], s["upper"], s["dedupe"])
    if s["skip_beyond_km"] > 0:
        if "Skip" not in header:
            raise RptsortError("input has no Skip column")
        for c in chans:
            if c.dist is not None:
                c.row["Skip"] = "S" if c.dist > s["skip_beyond_km"] else ""
    for i, c in enumerate(chans):
        c.row["Location"] = str(keep + 1 + i)

    zones = build_zones(
        chans, s["zones"], local_km=s["zone_local_km"], rings=s["rings"],
        rings_km=s["rings_km"], unit=s["units"], zone_max=s["zone_max"],
        name_len=s["name_len"], kept_locations=[int(r["Location"]) for r in kept],
        keep_zone=s["keep_zone"])

    # --- report
    unit, factor = s["units"], s["unit_factor"]
    lat, lon = center
    warn(f"Settings: {cfg_path or '(no settings file)'}" + (f"  preset={preset}" if preset else ""))
    rings = f" rings={','.join(f'{x:g}' for x in s['rings'])}{unit}" if s["sort"] == "rings" else ""
    warn(f"Center: {center_label} ({lat:.4f}, {lon:.4f})  sort={s['sort']}{rings}"
         f"  name={s['name']}  group_calls={s['group_calls']}")
    if not a.quiet:
        print_table(chans, unit, factor)
        if zones:
            print("\n" + format_zones(zones).rstrip())
            sys.stdout.flush()
    for name, n in ignored.items():
        if n:
            warn(f"\n{name}: ignored {n} non-repeater channel(s) at #1-{keep}.")
    if dup_count:
        warn(f"\nMerged {len(files)} files, dropped {dup_count} duplicate repeater(s).")
    if dropped:
        warn("\nFiltered out: " + ", ".join(f"{n} {why}" for why, n in dropped.items()))
    if over_limit:
        warn(f"\nlimit={s['limit']}: left out {len(over_limit)} channel(s), starting with: "
             + ", ".join(f"{c.call or c.row.get('Name', '')} {c.row.get('Frequency', '')}"
                         for c in over_limit[:5]))
    county = sorted({f"{c.town}, {c.state} (county: {c.county})"
                     for c in chans if c.src == "county"})
    if county:
        warn(f"\n{len(county)} town(s) not in Census list, used county center "
             "(pin exact spots under [coords]):")
        for t in county:
            warn(f"  {t}")
    lost = [c for c in chans if c.dist is None]
    if lost:
        warn(f"\n{len(lost)} channel(s) with no usable location (sorted last):")
        for c in lost:
            warn(f"  #{c.row['Location']} {c.row.get('Name', '')}"
                 f"  comment={(c.row.get('Comment') or '')[:50]!r}")
    if names["unnamed"]:
        warn(f"\n{len(names['unnamed'])} channel(s) kept their old name (no callsign or town):")
        for c in names["unnamed"]:
            warn(f"  #{c.row['Location']} {c.row.get('Name', '')}")
    if names["deduped"]:
        warn(f"\n{len(names['deduped'])} name(s) switched to frequency style to stay unique.")
    if names["cut"]:
        warn(f"\n{len(names['cut'])} name(s) cut to {s['name_len']} characters:")
        for c in names["cut"]:
            warn(f"  #{c.row['Location']} {c.row['Name']}  ({c.town})")
    if s["name"] != "keep":
        counts: dict[str, int] = {}
        for c in chans:
            counts[c.row.get("Name", "")] = counts.get(c.row.get("Name", ""), 0) + 1
        dupes = sorted(n for n, k in counts.items() if k > 1)
        if dupes:
            warn(f"\n{len(dupes)} name(s) used more than once (try --dedupe): {', '.join(dupes)}")

    first, last = keep + 1, keep + len(chans)
    if a.dry_run:
        warn(f"\nDry run: would keep {len(kept)} channel(s) and reorder #{first}-{last}. "
             "Nothing written.")
        return None
    out = a.output or files[0].with_name(f"{files[0].stem}-{preset or 'sorted'}.csv")
    if any(out.resolve() == f.resolve() for f in files):
        raise RptsortError("output would overwrite an input file; pick another -o path")
    write_csv(out, header, kept + [c.row for c in chans], newline)
    warn(f"\nWrote {out}: kept {len(kept)} channel(s), reordered #{first}-{last}.")
    if zones:
        zones_path = out.with_name(f"{out.stem}-zones.txt")
        zones_path.write_text(format_zones(zones), encoding="utf-8")
        warn(f"Wrote {zones_path} ({len(zones)} zones). Paste them into CHIRP's zone settings; "
             "zones are not part of the CSV.")
    return out


# ------------------------------------------------------------------ init command

def build_init_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rptsort init",
        description="Create a starter settings file. Asks for anything not given as a flag.",
    )
    p.add_argument("--home", help="your location: 'Town, ST' or 'lat,lon'")
    p.add_argument("--keep", type=int, help="channels at the top to leave untouched")
    p.add_argument("--name-len", type=int, help="longest channel name your radio accepts")
    p.add_argument("--units", choices=("km", "mi"))
    where = p.add_mutually_exclusive_group()
    where.add_argument("--path", type=Path, help=f"where to write (default {user_config_path()})")
    where.add_argument("--here", action="store_true", help="write ./rptsort.toml instead")
    where.add_argument("--print", dest="print_only", action="store_true",
                       help="print the file instead of writing it")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    return p


def ask(prompt: str, default: str) -> str:
    try:
        answer = input(f"{prompt} [{default}]: " if default else f"{prompt}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def run_init(argv: list[str]) -> Path | None:
    a = build_init_parser().parse_args(argv)
    interactive = sys.stdin.isatty() and not a.print_only

    home = a.home or (ask("Home location ('Town, ST' or 'lat,lon')", "") if interactive else "")
    if not home:
        raise RptsortError("need a home location: --home 'Town, ST' or --home 'lat,lon'")
    point = parse_latlon(home)
    if point is None:
        point = Geocoder(default_cache_dir()).locate_spec(home)
        warn(f"Found {home} at {point[0]:.4f}, {point[1]:.4f} (town center). "
             "Edit [home] for your exact spot.")

    def pick_int(value, prompt, default):
        if value is not None:
            return value
        if not interactive:
            return default
        text = ask(prompt, str(default))
        try:
            return int(text)
        except ValueError as exc:
            raise RptsortError(f"{prompt}: {text!r} is not a number") from exc

    keep = pick_int(a.keep, "Channels at the top to leave untouched (0 = none)", 0)
    name_len = pick_int(a.name_len, "Longest channel name your radio accepts", 16)
    units = a.units or (ask("Distance units, km or mi", "km") if interactive else "km")
    if units not in ("km", "mi"):
        raise RptsortError('units must be "km" or "mi"')

    text = render_template(point[0], point[1], keep, name_len, units)
    if a.print_only:
        sys.stdout.write(text)
        return None
    path = a.path or (Path.cwd() / "rptsort.toml" if a.here else user_config_path())
    if path.exists() and not a.force:
        raise RptsortError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    warn(f"Wrote {path}\nNext: rptsort mobile my-export.csv --dry-run")
    return path


# ------------------------------------------------------------------ entry point

def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        if argv and argv[0] == "init":
            run_init(argv[1:])
        else:
            run_sort(argv)
    except RptsortError as exc:
        warn(f"error: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
