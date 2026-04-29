# Scanning power on power meter versus signal generator power
import json
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter

nrx = NRXPowerMeter(delay=0)
signal = SignalGenerator(host="169.254.156.103", gpib=19)


freq_range = np.linspace(12e9, 15e9, 100)
power = -6
result = {
    "frequency": [],
    "power_meter": [],
}
initial_amp = signal.get_amplitude()
signal.set_amplitude(power)
signal.set_rf_output_state(True)
for freq in freq_range:
    amplitude = signal.get_amplitude()
    power = nrx.get_power()
    signal.set_frequency(freq)
    result["power_meter"].append(power)
    result["frequency"].append(freq)

signal.set_amplitude(initial_amp)


with open(
    f"meas_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json", "w", encoding="utf-8"
) as file:
    json.dump(result, file, indent=4, ensure_ascii=False)
