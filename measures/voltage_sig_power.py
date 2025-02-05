import json
import logging
import time
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Keithley.multimeter import Multimeter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

sg = SignalGenerator(host="169.254.156.103", gpib=19)
sg.set_power(-60)
sg.set_frequency(1e9)
sg.set_rf_output_state(True)

mult = Multimeter(host="169.254.156.103", gpib=26)
mult.set_function("F0")
mult.set_range("R2")

frequency_list = np.arange(1e9, 26e9, 1e9)
power_list = np.arange(-26, 10, 0.1)

data = []

try:
    for fstep, freq in enumerate(frequency_list, 1):
        sg.set_frequency(freq)
        _data = {
            "frequency": freq,
            "power": [],
            "voltage": [],
        }
        for pstep, power in enumerate(power_list, 1):
            sg.set_power(power)
            time.sleep(0.1)
            voltage = mult.get_voltage()
            _data["voltage"].append(voltage)
            _data["power"].append(power)
            print(
                f"[{pstep + fstep * len(power_list)}/{len(power_list)*(len(frequency_list))}] freq: {freq:.3f}; volt: {voltage:.3f}; power: {power:.3f}"
            )
        data.append(_data)
except (Exception, KeyboardInterrupt):
    ...

sg.set_power(-60)
sg.set_rf_output_state(False)

with open(
    f"meas_Ivan_Block_voltage_sig_power_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
