'''Fake blinka `board` module: named BCM pins D0-D27 and SPI.'''

board_id = "FAKEHW"


class Pin(object):
    def __init__(self, bcm):
        self.id = bcm
        self.name = "D%d" % bcm

    def __repr__(self):
        return "board.%s" % self.name


for _n in range(28):
    globals()["D%d" % _n] = Pin(_n)

# hardware spi0 pins on a raspberry pi
SCK = SCLK = globals()["D11"]
MOSI = globals()["D10"]
MISO = globals()["D9"]
CE0 = globals()["D8"]
CE1 = globals()["D7"]


def SPI():
    import busio
    return busio.SPI(SCK, MOSI=MOSI, MISO=MISO)
