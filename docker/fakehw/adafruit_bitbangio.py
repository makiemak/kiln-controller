'''Fake `adafruit_bitbangio` (software SPI on any three pins).'''

import busio


class SPI(busio.SPI):
    def __init__(self, clock, MOSI=None, MISO=None):
        pins = [p for p in (clock, MOSI, MISO) if p is not None]
        for p in pins:
            if not hasattr(p, "id"):
                raise ValueError("fakehw: %r is not a board pin" % (p,))
        if len(set(p.id for p in pins)) != len(pins):
            raise ValueError("fakehw: software SPI pins must be distinct: %r" % (pins,))
        super().__init__(clock, MOSI=MOSI, MISO=MISO)
