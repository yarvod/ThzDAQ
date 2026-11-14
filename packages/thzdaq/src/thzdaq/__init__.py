"""ThzDAQ for users and scripts: the client of thzdaq-api under one name.

    from thzdaq import connect, device, value

    bias = device("SIS bias", kind="sis_bias")     # declared: a form in the window
    voltage = value("Bias voltage", "2:3:51", unit="mV")

    lab = connect()
    with lab.measurement("pv_fine", devices=[bias], exclusive=[bias]) as m:
        for v in m.sweep(voltage):
            ...
"""

from thzdaq_api.data import Measured
from thzdaq_api.declare import device, instrument, plot, value
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Bench, Device, Readout, Run, connect
from thzdaq_api.measurement_file import Column, read_measurement
from thzdaq_api.raw import RawInstrument, reading, setting
from thzdaq_api.script import Cancelled, Session

__all__ = [
    "Bench",
    "Cancelled",
    "Column",
    "Device",
    "ErrorCode",
    "LabError",
    "Measured",
    "RawInstrument",
    "Readout",
    "Run",
    "Session",
    "connect",
    "device",
    "instrument",
    "plot",
    "read_measurement",
    "reading",
    "setting",
    "value",
]
