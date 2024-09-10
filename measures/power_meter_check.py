import json
import logging
import time
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from utils.functions import send_to_telegram

logger = logging.getLogger(__name__)

nrx = NRXPowerMeter(delay=0)
signal = SignalGenerator(host="169.254.156.103", gpib=19)

signal_amplitudes = np.linspace(-50, 20, 200)

data = {"powers": [], "amplitudes": signal_amplitudes.tolist()}

try:
    send_to_telegram(f"New measurement Power Meter check!")
    for amp in signal_amplitudes:
        signal.set_amplitude(amp)
        time.sleep(1)
        powers = []
        for i in range(5):
            nrx.get_power()
        for i in range(5):
            powers.append(nrx.get_power())
        powers_mean = np.mean(powers)
        logger.info(f"Amplitude {amp:.3}; Power {powers_mean:.3}")
        data["powers"].append(powers_mean)
    signal.set_amplitude(-40)
except (Exception, KeyboardInterrupt) as e:
    logger.error(f"Exception: {e}")
    send_to_telegram(f"Exception: {e}")
    signal.set_amplitude(-40)

with open(
    f"meas_power_check_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

send_to_telegram(f"Measurement successfully finished!")
