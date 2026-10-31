import csv
import tomllib

import pytest
from conftest import COUNTIES, DENVER, FACTORY, PLACES, REPEATERS, write_csv

from rptsort import RptsortError
from rptsort.channels import Chan, assign_names, freq_label
from rptsort.cli import main, run_init, run_sort
from rptsort.config import resolve_settings
from rptsort.geo import Geocoder, default_cache_dir, haversine_km

TOWN_COORDS = {name.rsplit(" ", 1)[0]: (lat, lon) for _, name, _, lat, lon in PLACES}
TOWN_COORDS["Rollinsville"] = next((lat, lon) for _, n, lat, lon in COUNTIES if n == "Gilpin County")


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def sort(*args, config):
    return run_sort([*map(str, args), "-c", str(config), "-q"])


def town(row):
    return row["Comment"].split(",")[0] if row["Comment"] else None


def dist_from(center, row):
    t = town(row)
    return haversine_km(*center, *TOWN_COORDS[t]) if t else float("inf")


# ------------------------------------------------------------ core behavior

def test_keeps_top_channels_and_renumbers(export, config):
    out = sort(export, config=config)
    src, rows = read(export), read(out)
    assert out.name == "export-sorted.csv"
    assert rows[:3] == src[:3]
    assert [r["Location"] for r in rows] == [str(i) for i in range(1, len(src) + 1)]

    def ident(r):
        return tuple(v for k, v in r.items() if k != "Location")

    assert sorted(map(ident, rows[3:])) == sorted(map(ident, src[3:]))


def test_distance_sort_nearest_first(export, config):
    rows = read(sort(export, config=config))[3:]
    dists = [dist_from(DENVER, r) for r in rows]
    assert dists == sorted(dists)
    assert [r["Frequency"] for r in rows[:2]] == ["147.000000", "147.210000"]  # Denver, by freq
    assert rows[-1]["Name"] == "SIMPLEX"  # no location -> last


def test_band_sort_is_frequency_order(export, config):
    rows = read(sort(export, "--sort", "band", config=config))[3:]
    freqs = [float(r["Frequency"]) for r in rows]
    assert freqs == sorted(freqs)


def test_rings_sort(export, config):
    rows = read(sort(export, "--sort", "rings", "--rings", "30", config=config))[3:]
    near = [r["Frequency"] for r in rows[:4]]
    assert near == ["146.880000", "147.000000", "147.210000", "444.625000"]
    rest = [float(r["Frequency"]) for r in rows[4:-1]]
    assert rest == sorted(rest)


def test_group_calls_keeps_callsigns_together(export, config):
    rows = read(sort(export, "--group-calls", config=config))[3:]
    calls = [r["Name"] for r in rows]
    blocks = [c for i, c in enumerate(calls) if i == 0 or calls[i - 1] != c]
    assert len(blocks) == len(set(blocks))
    assert calls[:3] == ["K0ABC"] * 3  # nearest repeater pulls its whole group up


def test_center_from_town(export, config):
    rows = read(sort(export, "--from", "Grand Junction, CO", config=config))[3:]
    assert rows[0]["Name"] == "KC0GJ"  # the Grand Junction repeater
    gj = TOWN_COORDS["Grand Junction"]
    dists = [dist_from(gj, r) for r in rows]
    assert dists == sorted(dists)


def test_center_from_latlon(export, config):
    rows = read(sort(export, "--from", "39.4817,-106.0384", config=config))[3:]
    assert town(rows[0]) == "Breckenridge"


# ------------------------------------------------------------ names

def names_by_freq(path):
    return {r["Frequency"]: r["Name"] for r in read(path)}


def test_town_band_names_abbreviate_then_cut(export, config):
    names = names_by_freq(sort(export, "--name", "town-band", config=config))
    assert names["147.000000"] == "DENVER 2M"
    assert names["145.170000"] == "MANITOU SPG 2M"  # 18 chars -> abbreviated
    assert names["443.625000"] == "BRECKENRIDG 70CM"  # 17 chars -> cut to 16
    assert names["146.520000"] == "SIMPLEX"  # no town -> unchanged


def test_call_formats(export, config):
    names = names_by_freq(sort(export, "--name", "call-town", config=config))
    assert names["147.000000"] == "K0ABC DENVER"
    names = names_by_freq(sort(export, "--name", "call-freq", "--no-upper", config=config))
    assert names["444.625000"] == "K0ABC 444.625"


def test_name_len_respected(export, config):
    for fmt in ("call-town", "town-band", "town-freq"):
        rows = read(sort(export, "--name", fmt, "--name-len", "10", config=config))
        assert all(len(r["Name"]) <= 10 for r in rows[3:])


def test_dedupe_makes_names_unique(export, config):
    rows = read(sort(export, "--name", "town-band", "--dedupe", config=config))[3:]
    names = [r["Name"] for r in rows]
    assert len(set(names)) == len(names)
    assert {"DENVER 147.0", "DENVER 147.21"} <= set(names)


def test_dedupe_numbers_exact_collisions():
    chans = [Chan(row={"Name": "X"}, freq=147.0, call="K0ABC", town="Denver") for _ in range(3)]
    assign_names(chans, "town-freq", 16, True, dedupe=True)
    assert [c.row["Name"] for c in chans] == ["DENVER 147.0", "DENVER 147.0 2", "DENVER 147.0 3"]


def test_freq_label():
    assert freq_label(147.21) == "147.21"
    assert freq_label(146.0) == "146.0"
    assert freq_label(444.625) == "444.625"


# ------------------------------------------------------------ skip, filters, limit

def skips(path):
    return {r["Frequency"]: r["Skip"] for r in read(path)[3:]}


def test_skip_beyond(export, config):
    s = skips(run_sort(["mobile", str(export), "-c", str(config), "-q"]))
    near = {"147.000000", "147.210000", "444.625000", "146.880000", "444.675000"}
    assert all(s[f] == "" for f in near)
    assert all(v == "S" for f, v in s.items() if f not in near and f != "146.520000")
    assert s["146.520000"] == ""  # unknown distance: Skip left alone


def test_miles(export, config, capsys):
    # 50 mi == 80.5 km, so same result as skip_beyond = 80 km
    out = run_sort(["miles", str(export), "-c", str(config)])
    assert skips(out) == skips(run_sort(["mobile", str(export), "-c", str(config), "-q"]))
    header = capsys.readouterr().out.splitlines()[0]
    assert " mi " in header


def test_filter_bands(export, config):
    rows = read(sort(export, "--bands", "2m", config=config))[3:]
    assert rows and all(float(r["Frequency"]) < 148 for r in rows)


def test_filter_open_only(export, config):
    freqs = {r["Frequency"] for r in read(sort(export, "--open-only", config=config))}
    assert "443.625000" not in freqs  # CLOSED
    assert "444.425000" not in freqs  # PRIVATE
    assert "147.000000" in freqs


def test_filter_max_distance(export, config):
    rows = read(sort(export, "--max-distance", "30", config=config))[3:]
    assert {town(r) for r in rows} == {"Denver", "Aurora", "Golden", None}


def test_limit(export, config):
    rows = read(sort(export, "--limit", "2", config=config))
    assert len(rows) == 3 + 2


# ------------------------------------------------------------ merge

def test_merge_drops_duplicates_and_extra_factory_rows(export, trip, config):
    rows = read(sort(export, trip, config=config))
    freqs = [r["Frequency"] for r in rows[3:]]
    assert freqs.count("147.000000") == 1  # in both files
    assert "444.350000" in freqs  # only in the trip file
    assert len(rows) == 3 + len(REPEATERS) + 1


# ------------------------------------------------------------ geocoding

def test_county_fallback_and_override():
    geo = Geocoder(default_cache_dir())
    assert geo.locate("Denver", "Colorado")[2] == "town"
    assert geo.locate("Rollinsville", "Colorado", "Gilpin")[2] == "county"
    assert geo.locate("Nowhere", "Colorado") is None
    geo = Geocoder(default_cache_dir(), {"Rollinsville, CO": [39.92, -105.51]})
    assert geo.locate("Rollinsville", "Colorado", "Gilpin") == (39.92, -105.51, "override")


def test_bad_coords_override():
    with pytest.raises(RptsortError):
        Geocoder(default_cache_dir(), {"Rollinsville": [1, 2]})


# ------------------------------------------------------------ config and safety

def test_unknown_setting_rejected():
    with pytest.raises(RptsortError, match="unknown setting"):
        resolve_settings({"defaults": {"skip_beyond_km": 5}}, None, {})


def test_bad_values_rejected():
    for table in ({"sort": "random"}, {"units": "ft"}, {"bands": ["2X"]}, {"keep": True}):
        with pytest.raises(RptsortError):
            resolve_settings({"defaults": table}, None, {})


def test_unknown_preset(export, config):
    with pytest.raises(RptsortError, match="not a CSV file or a preset"):
        run_sort(["nope", str(export), "-c", str(config)])


def test_no_home_needs_from(export, tmp_path):
    cfg = tmp_path / "nohome.toml"
    cfg.write_text("[defaults]\nkeep = 3\n")
    with pytest.raises(RptsortError, match="no home location"):
        sort(export, config=cfg)
    assert sort(export, "--from", "Grand Junction, CO", config=cfg)


def test_never_overwrites_input(export, config):
    with pytest.raises(RptsortError, match="overwrite"):
        sort(export, "-o", export, config=config)


def test_dry_run_writes_nothing(export, config, tmp_path):
    assert sort(export, "--dry-run", config=config) is None
    assert not (tmp_path / "export-sorted.csv").exists()


def test_crlf_and_quoting_preserved(tmp_path, config):
    src = write_csv(tmp_path / "crlf.csv", FACTORY + REPEATERS, newline="\r\n")
    out = sort(src, config=config).read_bytes()
    assert out.count(b"\r\n") == len(FACTORY + REPEATERS) + 1
    assert out.split(b"\r\n")[:4] == src.read_bytes().split(b"\r\n")[:4]
    assert b'"Denver, Colorado, Denver | Use: OPEN"' in out


def test_main_exit_code(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["missing.csv"])
    assert exc.value.code == 1
    assert "error:" in capsys.readouterr().err


# ------------------------------------------------------------ init

def test_init_print(capsys):
    run_init(["--print", "--home", "39.7,-105.0", "--keep", "25", "--units", "mi"])
    cfg = tomllib.loads(capsys.readouterr().out)
    assert cfg["home"] == {"lat": 39.7, "lon": -105.0}
    assert cfg["defaults"]["keep"] == 25
    assert cfg["defaults"]["units"] == "mi"
    assert cfg["presets"]["mobile"]["skip_beyond"] == 50
    for name in cfg["presets"]:
        resolve_settings(cfg, name, {})  # every example preset is valid


def test_init_home_by_town(capsys):
    run_init(["--print", "--home", "Denver, CO"])
    cfg = tomllib.loads(capsys.readouterr().out)
    assert (cfg["home"]["lat"], cfg["home"]["lon"]) == pytest.approx(DENVER)


def test_init_here_then_autodiscovered(export, tmp_path):
    path = run_init(["--here", "--home", "Denver, CO", "--keep", "3"])
    assert path == tmp_path / "rptsort.toml"
    with pytest.raises(RptsortError, match="already exists"):
        run_init(["--here", "--home", "Denver, CO"])
    run_init(["--here", "--home", "Denver, CO", "--keep", "3", "--force"])
    out = run_sort(["mobile", str(export), "-q"])  # finds ./rptsort.toml by itself
    assert read(out)[:3] == read(export)[:3]


def test_init_default_path_is_xdg(tmp_path):
    path = run_init(["--home", "Denver, CO"])
    assert path == tmp_path / "xdg" / "rptsort" / "config.toml"
