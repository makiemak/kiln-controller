'''Fake `digitalio`: pins remember their value, and the heater relay pin
(config.gpio_heat) drives the fake kiln's element.'''

import _model


class Direction(object):
    INPUT = "input"
    OUTPUT = "output"


class Pull(object):
    UP = "up"
    DOWN = "down"


class DigitalInOut(object):
    def __init__(self, pin):
        if pin is None or not hasattr(pin, "id"):
            raise ValueError("fakehw: %r is not a board pin" % (pin,))
        self.pin = pin
        self.direction = Direction.INPUT
        self.pull = None
        self._value = False

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = bool(value)
        if self.direction == Direction.OUTPUT and _model.is_heater_pin(self.pin):
            # gpio_heat_invert: the relay is energised when the pin
            # matches the configured "on" level
            invert = False
            try:
                import config
                invert = bool(getattr(config, "gpio_heat_invert", False))
            except Exception:
                pass
            _model.set_relay(self._value != invert)

    def switch_to_output(self, value=False, drive_mode=None):
        self.direction = Direction.OUTPUT
        self.value = value

    def switch_to_input(self, pull=None):
        self.direction = Direction.INPUT
        self.pull = pull

    def deinit(self):
        pass
