'''Fake `adafruit_max31855`, reading the fake kiln's temperature.'''

import _model


class MAX31855(object):
    def __init__(self, spi, cs):
        self.spi, self.cs = spi, cs

    def _read(self):
        name = _model.fault()
        if name == "open_tc":
            raise RuntimeError("thermocouple not connected")
        return _model.read_celsius()

    @property
    def temperature(self):
        return self._read()

    @property
    def temperature_NIST(self):
        return self._read()

    @property
    def reference_temperature(self):
        return _model.AMBIENT
