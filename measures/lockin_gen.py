# Scanning lockin voltage versus signal generator frequency
import json
import time

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Keithley.power_supply import PowerSupply
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.SRS.LockIn_SR830 import LockIn
from store.state import state


signal = SignalGenerator(host=state.PROLOGIX_IP)
lockin = LockIn()

freq_range = np.linspace(12 * 1e9, 18 * 1e9, 30001)
result = {
    "freq": [],
    "voltage": [],
}
for freq in freq_range:
    signal.set_frequency(freq)
    fr = signal.get_frequency()
    time.sleep(0.5)
    volt = lockin.get_out3()
    result["freq"].append(fr)
    result["voltage"].append(volt)
    print(f"{volt}; freq {freq}")


with open("meas.json", "w", encoding="utf-8") as file:
    json.dump(result, file, indent=4, ensure_ascii=False)
