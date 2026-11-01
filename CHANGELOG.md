# Changelog

Versions are `YY.MM.N`. Each release lists the platform it was tested on.

## 25.10.3

Slack reminders show 12 hour time, like `3:40 PM`. Only `kiln-notify.py`
changes; kiln control is exactly as in 25.10.1.

### Compatibility

Same as 25.10.2.

## 25.10.2

Slack notifications. `lib/`, `kiln-controller.py`, `config.py` and the
profiles are unchanged, so kiln control is exactly as in 25.10.1 and an
existing install keeps its settings.

### Added

- **`kiln-notify.py`**, a separate service that sends slack messages:
  firings starting and finishing, firings ending early, the controller
  not responding, the kiln not heating, the kiln far from its target,
  and temperature rising with no firing running. It only listens, so
  stopping it cannot affect a firing. See `docs/notifications.md`.
- **Calibration reminders:** chosen profiles get a "get ready" message
  before each hold and a "read the front thermometer now" message near
  its end, with the web reading at that moment.

### Changed

- README: a "This fork" section, and Celsius-first `temp_scale` wording.

### Compatibility

| | |
|---|---|
| Raspberry Pi OS | Bookworm (Debian 12) |
| Python | 3.11.2 (system `/usr/bin/python3`, venv from `requirements.txt`) |
| Hardware | Raspberry Pi 3 Model B, aarch64, MAX31856 with a type R thermocouple, software SPI |
| Dependencies | same as 25.10.0 (`pi-freeze-25.10.txt`) |
| Not compatible | Trixie (Debian 13) with its system Python 3.13 |

## 25.10.1

Safety fixes for the 25.10 baseline. No changes to `config.py` or the
profiles, so an existing install keeps its settings when it checks out
this tag.

### Fixed

- **The relay is switched off if the control loop fails.** Before, any
  unexpected error stopped the control thread, emergency checks
  included, and could leave the relay on while the web UI kept looking
  normal. The loop now switches the relay off first, then aborts the
  run and keeps running. A pause or resume sent in the wrong state is
  rejected, and a paused or running oven with no profile returns to
  idle. Based on upstream `03371d7`; switching the relay off directly
  first is new here.
- **A failing thermocouple read can no longer freeze the temperature.**
  An SPI/bus error or a nan reading used to kill the sensor thread, so
  the oven kept heating against the last temperatures. Failed reads now
  count as errors, so the too-many-errors check aborts the run. New
  here; not fixed upstream.
- **Crashes in profile and PID math:** at exactly the end of a profile
  (upstream `666def1`), a flat profile segment, a zero PID time step or
  `pid_ki = 0` (upstream `001a985`, `13b2c1f`).
- **Firing time is immune to clock changes.** Elapsed time and the PID
  use the monotonic clock, so a daylight-saving change or the clock
  jump when the Pi (which has no real-time clock) syncs NTP after boot
  can no longer skip or repeat part of a firing. The PID also keeps
  sub-second precision. Replaces upstream `1ca72d4` and `37804dc`.

### Compatibility

| | |
|---|---|
| Raspberry Pi OS | Bookworm (Debian 12) |
| Python | 3.11.2 (system `/usr/bin/python3`, venv from `requirements.txt`) |
| Hardware | Raspberry Pi 3 Model B, aarch64, MAX31856 with a type R thermocouple, software SPI |
| Dependencies | same as 25.10.0 (`pi-freeze-25.10.txt`) |
| Not compatible | Trixie (Debian 13): system Python is 3.13 |

Tested in docker with the Pi's Python 3.11.2 and exact packages, using
the kiln's own config and fake GPIO/SPI hardware (fault injection
included), before being installed on the kiln.

## 25.10.0

Baseline: upstream [jbruce12000/kiln-controller](https://github.com/jbruce12000/kiln-controller)
at `a2b3071`, unchanged. Proven on the kiln in firings from September
2025 to September 2026.

### Known issues (fixed in 25.10.1)

- The relay can be left on if the control loop crashes.
- A daylight-saving change disturbs a running firing.

### Compatibility

| | |
|---|---|
| Raspberry Pi OS | Bookworm (Debian 12), kiln-tested |
| Python | 3.11.2 (system `/usr/bin/python3`, venv from `requirements.txt`) |
| Hardware | Raspberry Pi 3 Model B, aarch64, MAX31856 with a type R thermocouple, software SPI |
| Dependencies | `pi-freeze-25.10.txt` (attached to the release) |
| Not compatible | Trixie (Debian 13): system Python is 3.13 |
