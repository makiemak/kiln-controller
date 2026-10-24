'''Shared state for the fake hardware: a small two-node thermal model of
the kiln, the heater relay, and fault injection.

The relay pin (digitalio) switches the element on and off; the fake
thermocouple chip (adafruit_max31856 / adafruit_max31855) reads the
kiln temperature from here. Everything runs in real time unless
FAKEHW_SPEEDUP is set.

Environment:
  FAKEHW_WATTS       element power in W (default 3200)
  FAKEHW_AMBIENT     room temperature in degC (default 18)
  FAKEHW_SPEEDUP     multiply physics time, e.g. 10 heats 10x faster (default 1)
  FAKEHW_FAULT       fault to inject from the start (see FAULTS)
  FAKEHW_FAULT_FILE  file holding a fault name, re-read on every sensor
                     read so a fault can be switched on while running
                     (default /run-data/fakehw-fault)
  FAKEHW_RELAY_FILE  file the relay state is written to on every change,
                     for tests to check (default /run-data/fakehw-relay)
'''

import logging
import math
import os
import threading
import time

log = logging.getLogger("fakehw")

# max31856 fault flags, plus two read failures:
#   oserror - the SPI read raises, like a bus/wiring error
#   nan     - the chip returns nan
FAULTS = ("cj_range", "tc_range", "cj_high", "cj_low", "tc_high", "tc_low",
          "voltage", "open_tc", "oserror", "nan")

WATTS = float(os.environ.get("FAKEHW_WATTS", 3200))
AMBIENT = float(os.environ.get("FAKEHW_AMBIENT", 18))
SPEEDUP = float(os.environ.get("FAKEHW_SPEEDUP", 1))
FAULT_FILE = os.environ.get("FAKEHW_FAULT_FILE", "/run-data/fakehw-fault")
RELAY_FILE = os.environ.get("FAKEHW_RELAY_FILE", "/run-data/fakehw-relay")

# same constants as the kiln-controller simulator (config.sim_*)
C_HEAT = 500.0    # J/K heat capacity of the element
C_OVEN = 5000.0   # J/K heat capacity of the kiln
R_HO = 0.1        # K/W element -> kiln
R_O = 0.5         # K/W kiln -> room

_lock = threading.Lock()
_t_oven = AMBIENT
_t_heat = AMBIENT
_last = time.monotonic()
_relay_on = False
_heater_pin = None


def set_heater_pin(pin):
    global _heater_pin
    _heater_pin = pin


def is_heater_pin(pin):
    if _heater_pin is not None:
        return pin is _heater_pin
    try:
        import config
        return pin is getattr(config, "gpio_heat", None)
    except Exception:
        return False


def _advance():
    '''integrate the model up to now. call with _lock held.'''
    global _t_oven, _t_heat, _last
    now = time.monotonic()
    elapsed = (now - _last) * SPEEDUP
    _last = now
    while elapsed > 0:
        dt = min(elapsed, 0.1)
        elapsed -= dt
        if _relay_on:
            _t_heat += WATTS * dt / C_HEAT
        p_ho = (_t_heat - _t_oven) / R_HO
        _t_oven += p_ho * dt / C_OVEN
        _t_heat -= p_ho * dt / C_HEAT
        _t_oven -= (_t_oven - AMBIENT) / R_O * dt / C_OVEN


def set_relay(on):
    global _relay_on
    with _lock:
        _advance()
        if on == _relay_on:
            return
        _relay_on = on
        temp = _t_oven
    log.info("fakehw relay %s at %.1f degC" % ("ON" if on else "OFF", temp))
    try:
        with open(RELAY_FILE, "w") as f:
            f.write("%s %.3f %.1f\n" % ("ON" if on else "OFF", time.time(), temp))
    except OSError:
        pass


def relay_on():
    return _relay_on


def temperature():
    with _lock:
        _advance()
        return _t_oven


def set_temperature(temp):
    '''force the kiln (and element) to a temperature, for tests.'''
    global _t_oven, _t_heat
    with _lock:
        _advance()
        _t_oven = _t_heat = float(temp)


def fault():
    '''the fault currently injected, or None.'''
    name = os.environ.get("FAKEHW_FAULT", "").strip()
    try:
        with open(FAULT_FILE) as f:
            name = f.read().strip()
    except OSError:
        pass
    if name in FAULTS:
        return name
    if name and name != "none":
        log.warning("fakehw: unknown fault %r ignored" % name)
    return None


def read_celsius():
    '''what the thermocouple chip reports, honouring injected faults.'''
    name = fault()
    if name == "oserror":
        raise OSError(5, "fakehw: injected SPI read error")
    if name == "nan":
        return math.nan
    return temperature()
