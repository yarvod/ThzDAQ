import json
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from store.state import state
from utils.functions import linear

signal = SignalGenerator(host="169.254.156.103", gpib=18)
nrx = NRXPowerMeter(delay=0)
ni_yig = NiYIGManager(host="169.254.0.86")


result = []

if_range = np.linspace(3e9, 13e9, 200)

try:

    for if_freq in if_range:
        print(f"[{if_freq:.3}]")
        signal.set_frequency(if_freq)
        freq_if_range = np.linspace(if_freq - 1e8, if_freq + 1e8, 100)
        _res = {
            "generator_freq": if_freq,
            "freq_if_range": freq_if_range.tolist(),
            "power": [],
        }
        for freq in freq_if_range:
            value = int(
                linear(
                    freq,
                    *state.CALIBRATION_DIGITAL_FREQ_2_POINT,
                )
            )
            resp = ni_yig.write_task(value=value)
            power = nrx.get_power()
            _res["power"].append(power)

        result.append(_res)
except (Exception, BaseException, KeyboardInterrupt) as e:
    print(f"Exception: {e}")


with open(
    f"meas_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json", "w", encoding="utf-8"
) as file:
    json.dump(result, file, indent=4, ensure_ascii=False)
