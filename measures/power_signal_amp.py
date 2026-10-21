# Scanning power on power meter versus signal generator power
import json
import time
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter

nrx = NRXPowerMeter(delay=0)
signal = SignalGenerator(host="169.254.156.103", gpib=19)


power_range = np.linspace(-60, 10)
result = {
    "power_source": [],
    "power_meter": [],
}
signal.set_frequency(14e9)
# initial_amp = signal.get_amplitude()
signal.set_rf_output_state(True)
for power_source in power_range:
    signal.set_power(power_source)
    time.sleep(0.1)
    power = nrx.get_power()

    result["power_meter"].append(power)
    result["power_source"].append(power_source)

# signal.set_amplitude(initial_amp)


with open(
    f"meas_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json", "w", encoding="utf-8"
) as file:
    json.dump(result, file, indent=4, ensure_ascii=False)
