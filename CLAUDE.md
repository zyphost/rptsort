# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`rptsort` is a stdlib-only Python CLI (3.11+, needs `tomllib`) that reorders, renames and scan-skips ham radio repeater channels in CSV files exported from CHIRP. Repeater locations come from the RepeaterBook comment CHIRP stores in each row (`Town, State, County | ... | Use: OPEN`), looked up in the US Census Gazetteer. No runtime dependencies. Keep it that way.

## Commands

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"   # dev setup
.venv/bin/pytest                                              # all tests
.venv/bin/pytest tests/test_rptsort.py::test_dedupe_makes_names_unique   # one test
.venv/bin/pytest -k merge                                     # by keyword
PYTHONPATH=src python3 -m rptsort --help                      # run without installing
```

There is no linter or formatter configured. The owner's `rptsort` command is a `pipx install -e .` of this checkout, so source edits are live immediately.

## Architecture

`cli.run_sort` is a single linear pipeline. Each stage lives in `channels.py`:

read CSV(s) → split rows into *kept* (`Location <= keep`, copied verbatim) and *movable* → `make_chan` (parse comment for town/state/county/`Use:`, regex the callsign out of `Name`, geocode, distance in km from center) → `drop_duplicates` (only when merging several files) → `apply_filters` → `sort_chans` → `group_by_call` → limit → `assign_names` → set `Skip` → renumber from `keep + 1` → `zones.build_zones` (needs final numbers) → report → write CSV, plus `FILE-PRESET-zones.txt` when `zones` is set.

- **Zones:** CHIRP's CSV format has no zones, so `zones.py` only produces text for pasting into CHIRP's zone settings. The `Local` zone in `local+state` mode is distance-based and spans states. Don't split it by state.

- **Output channel:** The report and warnings go to stderr. The channel table goes to stdout and is flushed before warnings.
- **CSV output:** The output must keep the input's column order, its line ending (CRLF or LF), and minimal quoting. Kept rows must come out byte-identical, and tests check this.
- **Merging:** In extra input files, rows at `Location <= keep` are dropped unless they look like repeaters (`is_repeater_row`).
- **Overwriting:** The output path may never equal any input path.

**Settings** (`config.py`): Values are layered `DEFAULTS` < `[defaults]` < `[presets.NAME]` < CLI flags. A flag value of `None` means the flag wasn't given. `resolve_settings` rejects unknown keys and wrong types, and converts user-unit distances (`units = "km" | "mi"`) into derived `*_km` keys that the pipeline uses.
- **Adding a setting** means touching all of these: `DEFAULTS`, `TYPES`, the argparse flag plus the tuple in `cli_overrides`, the comment block in `config_template.toml`, and the README tables.
- **Config lookup** uses the first file found: `--config`, then `./rptsort.toml`, then `$XDG_CONFIG_HOME/rptsort/config.toml`.
- **Gazetteer cache** lives in `$RPTSORT_CACHE`, or `$XDG_CACHE_HOME/rptsort` if that's unset.

**`init` subcommand:** `main()` dispatches on `argv[0] == "init"` by hand, because the `[PRESET] FILE...` positionals conflict with argparse subparsers. That makes `init` a reserved word. It renders `config_template.toml` with `string.Template`, so a literal `$` in the template must be written `$$`. The rendered file must parse, and every example preset must pass `resolve_settings` (a test checks both).

**Geocoding** (`geo.py`) reads the 2024 Census place and county Gazetteer zips, downloaded once. It strips Census place suffixes (`city`, `town`, `CDP`, and so on) and normalizes St/Mt/Ft, and an incorporated place beats a CDP of the same name. Lookup order is `[coords]` overrides, then town, then county center. County-located rows are marked `~` in the table. Locations are US only.

**Naming:** `NAME_FORMATS` maps each format to pieces (`call`, `town`, `band`, `freq`). Only the town piece is shortened to fit `name_len`: it's abbreviated first (`ABBREVIATIONS`), then truncated. Dedupe swaps `band` for `freq`, or appends `freq`, on colliding names only, and then numbers any names that still collide.

**Errors:** Raise `RptsortError` for anything the user can fix. `main()` prints `error: ...` and exits 1. `run_sort` and `run_init` return paths so tests can call them directly.

## Tests

- **No network:** The autouse `gazetteer` fixture in `tests/conftest.py` builds fake Gazetteer zips in `tmp_path`, sets `RPTSORT_CACHE` and `XDG_CONFIG_HOME`, and `chdir`s into `tmp_path`.
- **Shared data:** Sample CSV rows and constants are imported straight from `conftest`.
- **Writing fixtures:** Use `write_bytes`, never `write_text`. Windows newline translation breaks the CRLF test otherwise.
- **CI:** Runs pytest on Ubuntu with Python 3.11 through 3.14, plus macOS and Windows on 3.13.

## Privacy: keep examples generic

The owner's personal settings, including exact home coordinates, live outside this repo, and their real region must not appear in it.
- **Examples:** Docs, tests and commit messages use Denver-area towns and made-up callsigns (`K0ABC`, `W0XYZ`). Keep new examples in that style. Don't use real local repeaters or callsigns.
- **Ignored files:** `.gitignore` excludes `rptsort.toml`, `config.toml`, `*.csv` and `*.img`. Don't force-add them.

## Repo rules and releases

- **Protection on `main`:** Rulesets block force-push and deletion for everyone. A second ruleset ("main: CI must pass") requires the 6 CI jobs by name, e.g. `test (ubuntu-latest, 3.11)`, and the repo admin can bypass it.
  - **If the CI job matrix or names change,** update that ruleset with `gh api repos/zyphost/rptsort/rulesets`. Otherwise pull requests wait forever on checks that never run.
- **Releases:** The version lives only in `src/rptsort/__init__.py`, which hatch reads dynamically. To release, bump the version, commit, run `git tag -a vX.Y.Z`, push the tag, then run `gh release create vX.Y.Z --verify-tag`.
