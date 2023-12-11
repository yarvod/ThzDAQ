import json
import logging
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter


logger = logging.getLogger(__name__)

signal_lo = SignalGenerator(host="169.254.156.103", gpib=19)
signal_s = SignalGenerator(host="169.254.156.103", gpib=18)
nrx = NRXPowerMeter(delay=0)


if_freq = 6e9
lo_start = 14e9
lo_stop = 15e9
lo_steps = 100

lo_range = np.linspace(lo_start, lo_stop, lo_steps)
data = {
    "if": if_freq,
    "lo_freq": [],
    "s_freq": [],
    "power": [],
}
try:
    for step, freq in enumerate(lo_range):
        signal_lo.set_frequency(freq)
        signal_freq = freq * 18 + if_freq
        signal_s.set_frequency(signal_freq)
        power = nrx.get_power()
        data["lo_freq"].append(freq)
        data["s_freq"].append(signal_freq)
        data["power"].append(power)
except (Exception, KeyboardInterrupt) as e:
    logger.error(f"Exception: {e}")


with open(
    f"meas_teston_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
