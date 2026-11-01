import csv
import re

import pytest
from conftest import FACTORY, REPEATERS, row, write_csv

from rptsort import RptsortError
from rptsort.cli import run_sort
from rptsort.config import resolve_settings

CHEYENNE = row(15, "W7WYO", "146.940000", "-", "0.600000", "TSQL", "88.5", "100.0",
               "Cheyenne, Wyoming, Laramie | Use: OPEN")
ZONE_RE = re.compile(r"^Zone (\d+): (.+?)  \((\d+) channels\)$")


@pytest.fixture
def two_states(tmp_path):
    return write_csv(tmp_path / "zones.csv", FACTORY + REPEATERS + [CHEYENNE])


def sort(*args, config):
    return run_sort([*map(str, args), "-c", str(config), "-q"])


def zones_of(out):
    """Parse FILE-zones.txt into [(name, [channel numbers])]."""
    lines = out.with_name(f"{out.stem}-zones.txt").read_text(encoding="utf-8").splitlines()
    zones = []
    for i, line in enumerate(lines):
        m = ZONE_RE.match(line)
        if m:
            chans = [int(x) for x in lines[i + 1].split(", ")]
            assert int(m.group(3)) == len(chans)
            zones.append((m.group(2), chans))
    return zones


def towns(out):
    with open(out, newline="", encoding="utf-8") as fh:
        return {int(r["Location"]): (r["Comment"].split(",")[0] if r["Comment"] else None)
                for r in csv.DictReader(fh)}


def test_local_then_state(two_states, config):
    out = sort(two_states, "--zones", "local+state", "--zone-local", "30", config=config)
    zones, where = zones_of(out), towns(out)
    assert [name for name, _ in zones] == ["Local", "Colorado", "Wyoming", "Other"]
    by_name = {name: {where[c] for c in chans} for name, chans in zones}
    assert by_name["Local"] == {"Denver", "Aurora", "Golden"}
    assert by_name["Wyoming"] == {"Cheyenne"}
    assert by_name["Other"] == {None}
    # every reordered channel is in exactly one zone, in CSV (distance) order
    listed = [c for _, chans in zones for c in chans]
    assert sorted(listed) == list(range(4, 4 + len(REPEATERS) + 1))
    assert all(chans == sorted(chans) for _, chans in zones)


def test_local_zone_spans_states(two_states, config):
    out = sort(two_states, "--zones", "local+state", "--zone-local", "200", config=config)
    zones, where = zones_of(out), towns(out)
    local = {where[c] for c in dict(zones)["Local"]}
    assert {"Denver", "Cheyenne"} <= local  # Local is by distance, not by state
    assert "Wyoming" not in dict(zones)


def test_zone_local_defaults_to_skip_beyond(export, config):
    out = run_sort(["mobile", str(export), "-c", str(config), "-q", "--zones", "local+state"])
    zones, where = zones_of(out), towns(out)
    assert {where[c] for c in dict(zones)["Local"]} == {"Denver", "Aurora", "Golden", "Rollinsville"}


def test_zone_max_splits(export, config):
    out = sort(export, "--zones", "state", "--zone-max", "4", config=config)
    assert [(n, len(c)) for n, c in zones_of(out)] == [
        ("Colorado 1", 4), ("Colorado 2", 4), ("Colorado 3", 2), ("Other", 1)]


def test_keep_zone(export, config):
    out = sort(export, "--zones", "state", "--keep-zone", "Simplex", config=config)
    assert zones_of(out)[-1] == ("Simplex", [1, 2, 3])


def test_ring_zones(export, config):
    out = sort(export, "--zones", "rings", config=config)
    assert [n for n, _ in zones_of(out)] == ["0-30 km", "30-80 km", "80+ km", "Other"]
    out = sort(export, "--zones", "rings", "--units", "mi", "--rings", "20,50", config=config)
    assert [n for n, _ in zones_of(out)][:2] == ["0-20 mi", "20-50 mi"]


def test_no_zones_by_default(export, config):
    out = sort(export, config=config)
    assert not out.with_name(f"{out.stem}-zones.txt").exists()


def test_dry_run_prints_zones_without_file(export, config, tmp_path, capsys):
    run_sort([str(export), "-c", str(config), "--dry-run", "--zones", "local+state"])
    assert "Zone 1: Local" in capsys.readouterr().out
    assert not list(tmp_path.glob("*-zones.txt"))


def test_bad_zone_settings():
    for table in ({"zones": "county"}, {"zone_max": 0}, {"zone_local": -1}):
        with pytest.raises(RptsortError):
            resolve_settings({"defaults": table}, None, {})
