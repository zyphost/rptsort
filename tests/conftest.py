"""Test fixtures: a tiny fake Census Gazetteer and sample CHIRP CSV files (no network).

Callsigns are made-up examples; town coordinates are approximate.
"""

import zipfile

import pytest

from rptsort.geo import GAZ_COUNTIES, GAZ_PLACES

PLACE_HEADER = ("USPS\tGEOID\tANSICODE\tNAME\tLSAD\tFUNCSTAT\tALAND\tAWATER\t"
                "ALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG          ")
PLACES = [
    ("CO", "Denver city", "A", 39.7392, -104.9849),
    ("CO", "Aurora city", "A", 39.7294, -104.8319),
    ("CO", "Golden city", "A", 39.7555, -105.2211),
    ("CO", "Colorado Springs city", "A", 38.8339, -104.8214),
    ("CO", "Manitou Springs city", "A", 38.8597, -104.9172),
    ("CO", "Breckenridge town", "A", 39.4817, -106.0384),
    ("CO", "Grand Junction city", "A", 39.0639, -108.5506),
    ("CO", "Fruita city", "A", 39.1589, -108.7290),
]
COUNTY_HEADER = ("USPS\tGEOID\tANSICODE\tNAME\tALAND\tAWATER\tALAND_SQMI\t"
                 "AWATER_SQMI\tINTPTLAT\tINTPTLONG          ")
COUNTIES = [
    ("CO", "Denver County", 39.7618, -104.8806),
    ("CO", "Gilpin County", 39.8580, -105.5279),
    ("CO", "Mesa County", 39.0180, -108.4640),
]

CSV_HEADER = ("Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,"
              "DtcsPolarity,RxDtcsCode,CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,"
              "RPT1CALL,RPT2CALL,DVCODE")
TAIL = "023,NN,023,Tone->Tone,FM,5.00,,5.0W"


def row(loc, name, freq, duplex, offset, tone, rtone, ctone, comment=""):
    comment = f'"{comment}"' if comment else ""
    return (f"{loc},{name},{freq},{duplex},{offset},{tone},{rtone},{ctone},"
            f"{TAIL},{comment},,,,")


FACTORY = [
    "1,Channel 1,430.012500,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,DMR,2.50,,5.0W,,,,,",
    "2,Channel 2,432.225000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,DMR,2.50,,5.0W,,,,,",
    "3,Channel 3,434.425000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,DMR,2.50,,5.0W,,,,,",
]
REPEATERS = [
    row(4, "N0DEF", "147.315000", "+", "0.600000", "TSQL", "88.5", "97.4",
        "Breckenridge, Colorado, Summit | Landmark: Peak 8 | Use: OPEN"),
    row(5, "W0XYZ", "145.350000", "-", "0.600000", "TSQL", "88.5", "162.2",
        "Colorado Springs, Colorado, El Paso | Use: OPEN"),
    row(6, "K0ABC", "147.000000", "+", "0.600000", "Tone", "100.0", "88.5",
        "Denver, Colorado, Denver | Use: OPEN"),
    row(7, "K0ABC", "444.625000", "+", "5.000000", "TSQL", "88.5", "91.5",
        "Golden, Colorado, Jefferson | Use: OPEN"),
    row(8, "W0XYZ", "146.880000", "-", "0.600000", "TSQL", "88.5", "91.5",
        "Aurora, Colorado, Arapahoe | Use: OPEN"),
    row(9, "N0DEF", "443.625000", "+", "5.000000", "TSQL", "88.5", "97.4",
        "Breckenridge, Colorado, Summit | Use: CLOSED"),
    row(10, "KD0AAA", "145.170000", "-", "0.600000", "", "88.5", "88.5",
        "Manitou Springs, Colorado, El Paso | Use: OPEN"),
    row(11, "KC0RRR", "444.675000", "+", "5.000000", "TSQL", "88.5", "88.5",
        "Rollinsville, Colorado, Gilpin | Use: OPEN"),
    row(12, "KC0GJ", "444.425000", "+", "5.000000", "Tone", "88.5", "88.5",
        "Grand Junction, Colorado, Mesa | Use: PRIVATE"),
    row(13, "K0ABC", "147.210000", "+", "0.600000", "TSQL", "88.5", "91.5",
        "Denver, Colorado, Denver | Use: OPEN"),
    "14,SIMPLEX,146.520000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,5.0W,,,,,",
]
# A second export (e.g. pulled around a trip destination): same factory channels,
# one repeater that is also in the first file, and one new one.
TRIP = [
    row(4, "K0ABC", "147.000000", "+", "0.600000", "Tone", "100.0", "88.5",
        "Denver, Colorado, Denver | Use: OPEN"),
    row(5, "N0JKL", "444.350000", "+", "5.000000", "TSQL", "88.5", "88.5",
        "Fruita, Colorado, Mesa | Use: OPEN"),
]

DENVER = (39.7392, -104.9849)

CONFIG = f"""
[home]
lat = {DENVER[0]}
lon = {DENVER[1]}

[defaults]
keep = 3

[presets.mobile]
name = "town-band"
skip_beyond = 80

[presets.miles]
units = "mi"
skip_beyond = 50
"""


def write_csv(path, lines, newline="\n"):
    # write_bytes: no newline translation on Windows
    path.write_bytes((newline.join([CSV_HEADER, *lines]) + newline).encode("utf-8"))
    return path


@pytest.fixture(autouse=True)
def gazetteer(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    with zipfile.ZipFile(cache / GAZ_PLACES, "w") as zf:
        lines = [PLACE_HEADER] + [f"{st}\t0\t0\t{name}\t25\t{fs}\t1\t0\t1\t0\t{lat}\t{lon}"
                                  for st, name, fs, lat, lon in PLACES]
        zf.writestr("2024_Gaz_place_national.txt", "\n".join(lines) + "\n")
    with zipfile.ZipFile(cache / GAZ_COUNTIES, "w") as zf:
        lines = [COUNTY_HEADER] + [f"{st}\t0\t0\t{name}\t1\t0\t1\t0\t{lat}\t{lon}"
                                   for st, name, lat, lon in COUNTIES]
        zf.writestr("2024_Gaz_counties_national.txt", "\n".join(lines) + "\n")
    monkeypatch.setenv("RPTSORT_CACHE", str(cache))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    return cache


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "test.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def export(tmp_path):
    return write_csv(tmp_path / "export.csv", FACTORY + REPEATERS)


@pytest.fixture
def trip(tmp_path):
    return write_csv(tmp_path / "trip.csv", FACTORY + TRIP)
