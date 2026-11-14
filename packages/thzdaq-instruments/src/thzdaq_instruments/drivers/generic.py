"""Instruments without a driver of their own: only how they are reached.

Such an instrument reads and sets nothing by itself; what it does goes as raw
commands (lab.raw, thzdaq raw, the Advanced console of its dock), and a
script that declares it (instrument(...)) may name its replies and settings
(reading, setting). Each generic driver is one way to talk (text commands
here; serial frames or Modbus registers may follow) and has the device type
GENERIC, by which clients offer them apart from the drivers of models.
"""

from thzdaq_instruments.instrument import GENERIC, ScpiInstrument


class GenericScpi(ScpiInstrument):
    """Text commands, one line each, over any message based connection (a
    socket, serial, GPIB, VISA): SCPI or a protocol of its own."""

    driver_key = "generic.scpi"
    device_type = GENERIC
