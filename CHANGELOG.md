# Changelog

Notable changes to `rptsort`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `dedupe = "number"` and `--dedupe number` number channels that share a name, in
  channel order: `DENVER1`, `DENVER2`, `DENVER3`. Names are shortened to leave room
  for the number. Names that were already unique stay as they are. This is for radios
  that show only the name or only the frequency, not both.

### Changed

- `dedupe` takes `false`, `"number"`, or `true`/`"freq"` (frequency-style names, as
  before). `--dedupe` takes an optional mode and defaults to `freq`, and
  `--no-dedupe` still turns it off.
- The example presets from `rptsort init` and in the README use `dedupe = "number"`.

## [0.3.0] - 2026-11-14

### Added

- `zone_block` setting and `--zone-block` flag, for radios with fixed banks where a
  channel's number picks its bank (for example, 10 banks of 100 channels). Each zone
  starts at the top of its own bank. With `keep_zone`, the kept top channels move to a
  bank of their own. Without it, they stay where they are and the zones start in the
  next empty bank. Zones are split at the bank size, and `zone_max` is ignored. The
  zones file lists what each bank holds, for naming the banks in CHIRP.
- `power` setting and `--power` flag set Power on every channel, kept channels
  included, as `"10W"` or `10`. On import, CHIRP picks the radio's level closest to the
  CSV's watts, so `5.0W` lands on 3W on a radio with 10W, 3W and 1W levels.

### Changed

- The example presets from `rptsort init` and in the README use `name = "town"`. The
  band suffix is redundant when the radio shows the frequency, and leaving it off gives
  the town more room.
- When `zone_block` moves channels, the output CSV lists rows in channel order.
- CI uses `actions/setup-python` v7.

## [0.2.0] - 2026-10-31

### Added

- Zones, for radios (most DMR radios included) that only let you flip through the
  channels in the current zone. The `zones` setting takes one of these:
  - `local+state`: a `Local` zone with everything within `zone_local`, from any
    state, then one zone per state.
  - `state`: one zone per state.
  - `rings`: one zone per distance ring.
- Zone lists are printed after the channel table and saved as `FILE-PRESET-zones.txt`,
  ready to paste into CHIRP's zone settings. CHIRP's CSV format has no zones.
- `zone_max` splits big zones, and `keep_zone` adds a zone for the kept top channels.
- New flags: `--zones`, `--zone-local`, `--zone-max`, `--keep-zone`.

### Changed

- CI uses `actions/checkout` v7.

## [0.1.0] - 2026-10-31

First release.

### Added

- Sort by distance (nearest first), band, town, or distance rings, from home or from
  any town or lat,lon.
- Leave the first N channels untouched and renumber the rest.
- Name formats `call`, `call-town`, `call-band`, `call-freq`, `town`, `town-band` and
  `town-freq`. Names are fitted to the radio's name length, with optional dedupe.
- Group repeaters that share a callsign.
- Scan-skip or remove far repeaters, filter by band or open/closed status, and cap the
  channel count.
- Merge several exports and drop duplicate repeaters.
- Presets per radio in a TOML settings file. `rptsort init` writes a starter file.
- Distances in km or miles.
- Town coordinates from the US Census Gazetteer, downloaded once. Falls back to the
  county center, and `[coords]` overrides both.

[Unreleased]: https://github.com/zyphost/rptsort/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/zyphost/rptsort/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/zyphost/rptsort/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/zyphost/rptsort/releases/tag/v0.1.0
