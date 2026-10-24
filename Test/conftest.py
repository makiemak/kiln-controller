'''Make lib/oven.py and config.py importable without a raspberry pi.

On the pi (or in the docker rehearsal, which puts docker/fakehw on the
path) the real hardware modules import fine and nothing here is used.
Anywhere else, minimal stand-ins are installed so the tests can run.'''

import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for path in (ROOT, os.path.join(ROOT, 'lib')):
    if path not in sys.path:
        sys.path.insert(0, path)


class _Pin(object):
    def __init__(self, name):
        self.id = self.name = name


class _DigitalInOut(object):
    def __init__(self, pin):
        self.pin = pin
        self.direction = None
        self.value = False


class _SPI(object):
    def __init__(self, *args, **kwargs):
        pass


def _install_stubs():
    board = types.ModuleType('board')
    board.board_id = 'TEST'

    def _board_getattr(name):
        if name.startswith('D') and name[1:].isdigit():
            return _Pin(name)
        raise AttributeError(name)
    board.__getattr__ = _board_getattr
    board.SPI = _SPI

    digitalio = types.ModuleType('digitalio')
    digitalio.DigitalInOut = _DigitalInOut
    digitalio.Direction = types.SimpleNamespace(INPUT='input', OUTPUT='output')

    busio = types.ModuleType('busio')
    busio.SPI = _SPI

    bitbangio = types.ModuleType('adafruit_bitbangio')
    bitbangio.SPI = _SPI

    max31856 = types.ModuleType('adafruit_max31856')
    max31856.ThermocoupleType = types.SimpleNamespace(
        B=0, E=1, J=2, K=3, N=4, R=5, S=6, T=7)

    for module in (board, digitalio, busio, bitbangio, max31856):
        sys.modules[module.__name__] = module


try:
    import digitalio  # noqa: F401
    import adafruit_bitbangio  # noqa: F401
    import adafruit_max31856  # noqa: F401
except Exception:
    _install_stubs()
