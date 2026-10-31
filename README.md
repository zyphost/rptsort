# rptsort

Put the repeaters you can actually reach at the top of your radio's channel list.

When you import nearby repeaters from [RepeaterBook](https://www.repeaterbook.com/)
into [CHIRP](https://chirpmyradio.com/), they land in whatever order the query
returned. Flipping through 140 channels to find the one across town gets old fast.
`rptsort` takes the CSV you export from CHIRP and:

- **reorders** repeaters by distance from you, by band, by town, or in distance rings
- **leaves your first N channels alone** (simplex, calling, factory or DMR channels)
- **renames** channels so the display tells you something: `BOULDER 2M`, `K0ABC GOLDEN`, `DENVER 447.1`
- **groups** repeaters that share a callsign (club systems and linked networks)
- **scan-skips** far repeaters so scanning only stops on ones you can hit
- **filters** by distance, band, or open/closed status, and caps the channel count
- **merges** several exports (home + a trip) and drops the duplicates

Then you import the new CSV back into CHIRP and upload it to the radio.

Works with any radio CHIRP supports, including the browser-based CHIRP. No
dependencies beyond Python 3.11 or newer.

## Install

With [pipx](https://pipx.pypa.io/) (recommended):

```sh
pipx install git+https://github.com/zyphost/rptsort
```

Or from a clone, without installing anything:

```sh
git clone https://github.com/zyphost/rptsort
cd rptsort
PYTHONPATH=src python3 -m rptsort --help
```

## Quick start

1. **Create your settings file** (asks for your location, radio name length, and units):

   ```sh
   rptsort init
   ```

   This writes `~/.config/rptsort/config.toml`. Use `rptsort init --here` to put
   `rptsort.toml` in the current folder instead, which is handy if you keep your
   radio files in a synced folder.

2. **In CHIRP**, query RepeaterBook for repeaters near you, add them to your
   radio's channel list, and export the channel list to a CSV file.

3. **Preview the result:**

   ```sh
   rptsort mobile my-radio.csv --dry-run
   ```

   You'll see a table of the new order with each repeater's distance, tone and
   town, plus notes about anything it had to guess.

4. **Write it:**

   ```sh
   rptsort mobile my-radio.csv
   ```

   This creates `my-radio-mobile.csv` next to the original. The original is never
   changed.

5. **Import** the new CSV into CHIRP and upload it to the radio.

## Presets

Different radios want different layouts. The settings file holds one preset per
radio or situation, and you pick one by name:

```toml
[home]
lat = 39.7392
lon = -104.9849

[defaults]
keep = 25          # channels 1-25 are left exactly as they are
name_len = 16      # longest name the radio accepts

[presets.mobile]   # in the car: nearest first, short names, skip far ones
name = "town-band"
dedupe = true
skip_beyond = 80

[presets.base]     # at home: distance rings, grouped by callsign
sort = "rings"
rings = [30, 80]
name = "call-town"
group_calls = true

[presets.trip]     # sort around somewhere else
center = "Grand Junction, CO"
name = "town-band"
skip_beyond = 60
```

```sh
rptsort mobile my-radio.csv
rptsort base base-radio.csv
rptsort trip grand-junction.csv
```

Settings are applied in this order, later winning: built-in defaults, then
`[defaults]`, then the preset, then command-line flags. So
`rptsort mobile my-radio.csv --skip-beyond 40` uses the mobile preset with one change.

## Sort methods

| `sort` | Order |
|---|---|
| `distance` | Nearest first. Repeaters in the same town are listed by frequency. |
| `band` | All 2m repeaters, then all 70cm, each in frequency order. The classic printed-directory layout. |
| `town` | Alphabetical by town, then frequency. Good if you think in places. |
| `rings` | Distance groups (e.g. under 30, 30 to 80, beyond 80), each group in frequency order. |

`group_calls = true` works with any sort: all repeaters with the same callsign
are pulled together at the spot where the first one lands. A shared callsign
usually means one club owns them, which often but not always means they're linked.

## Channel names

| `name` | Example |
|---|---|
| `keep` | leave names as they are (default) |
| `call` | `K0ABC` |
| `call-town` | `K0ABC IDAHO SPG` |
| `call-band` | `K0ABC 2M` |
| `call-freq` | `K0ABC 145.17` |
| `town` | `IDAHO SPRINGS` |
| `town-band` | `IDAHO SPRINGS 2M` |
| `town-freq` | `IDAHO SPG 145.17` |

Names are fitted to `name_len`. Common words are abbreviated first (Springs to
SPG, Mountain to MTN, City to CTY), then the town is shortened if it still
doesn't fit. Set `upper = false` to keep mixed case.

With `dedupe = true`, channels that would end up with the same name (three
`DENVER 2M`, say) get frequency-style names instead (`DENVER 145.34`,
`DENVER 146.94`, `DENVER 147.33`). Names that were already unique stay as they are.

Callsigns are read from the channel name, so rename from a fresh RepeaterBook
import rather than from a file you already renamed to town-only names.

## Filters and limits

| Setting | Flag | What it does |
|---|---|---|
| `skip_beyond` | `--skip-beyond` | Mark channels farther than this as scan-skip. They stay in the list. |
| `max_distance` | `--max-distance` | Remove channels farther than this. |
| `bands` | `--bands 2M,70CM` | Keep only these bands. |
| `open_only` | `--open-only` | Remove repeaters RepeaterBook lists as CLOSED or PRIVATE. |
| `limit` | `--limit` | Keep at most this many reordered channels, after sorting. |
| `units` | `--units mi` | Use miles for the distances above, rings, and the table. |

## Merging exports

Give it more than one CSV and they're combined:

```sh
rptsort trip my-radio.csv grand-junction.csv
```

The first file supplies the kept channels at the top. Repeaters come from all
files, and a repeater that appears in several (same callsign, frequency, offset
and tones) is kept once. In the extra files, top channels that aren't repeaters
are ignored.

## How location works

CHIRP stores RepeaterBook's location in each channel's comment as
`Town, State, County | ...`. `rptsort` looks the town up in the
[US Census Gazetteer](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html),
a free list of every US town's coordinates. The list is downloaded once (about
1.4 MB) into `~/.cache/rptsort/`. Set `RPTSORT_CACHE` to put it somewhere else.

Distances are measured to the center of the town, not the repeater's tower,
which is usually close enough for ordering. When a town isn't in the Census
list, the county's center is used and the table marks it with `~`. To pin an exact
spot:

```toml
[coords]
"Rollinsville, CO" = [39.92, -105.51]
```

Channels with no location in their comment (simplex channels, ones you added by
hand) are kept and placed at the end.

**Limits:** US locations only, and the comment must be in RepeaterBook's format.

## Privacy

Your settings file contains your home coordinates. Keep it out of public
repositories. This repo's `.gitignore` excludes `rptsort.toml` and `config.toml`
for that reason. `rptsort init` uses the center of the town you give it, so you
can also choose not to store your exact location at all.

## All options

```
rptsort [PRESET] FILE.csv [MORE.csv ...] [options]
rptsort init [--home PLACE] [--keep N] [--name-len N] [--units km|mi]
             [--here | --path FILE | --print] [--force]
```

Run `rptsort --help` or `rptsort init --help` for the full list.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

Tests use a small fake town list and never touch the network.

## License

MIT. See [LICENSE](LICENSE).

Not affiliated with CHIRP or RepeaterBook.
