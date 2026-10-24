# Changelog

Versions are `YY.MM.N`. Each release lists the platform it was tested on.

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
