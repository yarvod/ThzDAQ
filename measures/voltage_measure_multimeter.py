import json
import logging
from datetime import datetime

import numpy as np

from api.Keithley.multimeter import Multimeter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

mult = Multimeter(host="169.254.156.103", gpib=26)
mult.set_function("F0")
mult.set_range("R1")

time_list = np.arange(0, 1, 0.001)
time_end = 600

data = {
    "voltage": [],
    "time": [],
}

try:
    for tstep, time_counter in enumerate(time_list, 1):
        voltage = mult.get_voltage()
        data["voltage"].append(voltage)
        time_now = datetime.now().strftime("%T.%f")
        data["time"].append(time_now)
        # print(f"[{tstep}/{len(time_list)}] time: {time_now}; volt: {voltage:.3f}")
except (Exception, KeyboardInterrupt):
    ...

with open(
    f"meas_Ivan_Block_voltage_sig_power_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
