'''Fake `busio` (hardware SPI).'''


class SPI(object):
    def __init__(self, clock, MOSI=None, MISO=None):
        self.clock, self.MOSI, self.MISO = clock, MOSI, MISO

    def try_lock(self):
        return True

    def unlock(self):
        pass

    def configure(self, **kwargs):
        pass

    def deinit(self):
        pass
