# Scanning voltage on power meter versus signal generator power
import json
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Keithley.power_supply import PowerSupply
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter

nrx = NRXPowerMeter(delay=0)
keithley = PowerSupply(host="169.254.156.103", gpib=22)
signal = SignalGenerator(host="169.254.156.103", gpib=19)


amp_range = np.linspace(-49, 25, 100)
result = {
    "amp": [],
    "power": [],
    "voltage": [],
}
initial_amp = signal.get_amplitude()
for amp in amp_range:
    signal.set_amplitude(amp)
    amplitude = signal.get_amplitude()
    power = nrx.get_power()
    voltage = keithley.get_voltage()
    result["amp"].append(amplitude)
    result["power"].append(power)
    result["voltage"].append(voltage)

signal.set_amplitude(initial_amp)


with open(
    f"meas_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json", "w", encoding="utf-8"
) as file:
    json.dump(result, file, indent=4, ensure_ascii=False)
