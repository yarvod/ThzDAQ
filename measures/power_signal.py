# Scanning voltage on power meter versus signal generator power
import json

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Keithley.power_supply import PowerSupply
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from store.state import state

nrx = NRXPowerMeter()
keithley = PowerSupply()
signal = SignalGenerator(host=state.PROLOGIX_IP)


amp_range = np.linspace(-49, 25, 100)
result = {
    "amp": [],
    "power": [],
    "voltage": [],
}
for amp in amp_range:
    signal.set_amplitude(amp)
    amplitude = signal.get_amplitude()
    power = nrx.get_power()
    voltage = keithley.get_voltage()
    result["amp"].append(amplitude)
    result["power"].append(power)
    result["voltage"].append(voltage)


with open("meas.json", "w", encoding="utf-8") as file:
    json.dump(result, file, indent=4, ensure_ascii=False)
