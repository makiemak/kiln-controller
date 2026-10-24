'''Fake `adafruit_max31856`: same constructor, properties and fault keys
as the real driver, reading the fake kiln's temperature.'''

import _model


class ThermocoupleType(object):
    B = 0b0000
    E = 0b0001
    J = 0b0010
    K = 0b0011
    N = 0b0100
    R = 0b0101
    S = 0b0110
    T = 0b0111
    G8 = 0b1000
    G32 = 0b1100


_TYPES = {getattr(ThermocoupleType, n): n for n in
          ("B", "E", "J", "K", "N", "R", "S", "T", "G8", "G32")}

FAULT_KEYS = ("cj_range", "tc_range", "cj_high", "cj_low",
              "tc_high", "tc_low", "voltage", "open_tc")


class MAX31856(object):
    def __init__(self, spi, cs, thermocouple_type=ThermocoupleType.K, baudrate=500000):
        if thermocouple_type not in _TYPES:
            raise ValueError("fakehw: unknown thermocouple type %r" % (thermocouple_type,))
        self.spi, self.cs = spi, cs
        self.thermocouple_type = thermocouple_type
        self._noise_rejection = 60
        self.averaging = 1
        _model.log.info("fakehw MAX31856 type %s" % _TYPES[thermocouple_type])

    @property
    def noise_rejection(self):
        return self._noise_rejection

    @noise_rejection.setter
    def noise_rejection(self, frequency):
        if frequency not in (50, 60):
            raise ValueError("noise_rejection must be either 50 or 60")
        self._noise_rejection = frequency
        _model.log.info("fakehw MAX31856 noise rejection %d Hz" % frequency)

    @property
    def temperature(self):
        return _model.read_celsius()

    @property
    def reference_temperature(self):
        return _model.AMBIENT

    @property
    def fault(self):
        name = _model.fault()
        return {k: (k == name) for k in FAULT_KEYS}

    def initiate_one_shot_measurement(self):
        pass

    @property
    def oneshot_pending(self):
        return False
