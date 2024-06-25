import json
import time
from datetime import datetime

import numpy as np

from api import SpectrumBlock
from api.Scontel.sis_block import SisBlock

bias_range = np.linspace(3e-3, 8e-3, 400)

sis_block = SisBlock()
sis_block.connect()

spectrum = SpectrumBlock(host="169.254.75.176", port=5025)

data = []

try:

    for i, voltage in enumerate(bias_range, 1):
        print(f"Voltage set {voltage:.3}")
        sis_block.set_bias_voltage(voltage)
        time.sleep(0.5)
        voltage_get = sis_block.get_bias_voltage()
        print(f"{i}/300; Voltage set {voltage:.3}; Voltage get {voltage_get:.3}")
        current_get = sis_block.get_bias_current()
        spectr_points, spectr_freq = spectrum.get_trace_data(start=2, stop=14)

        data.append(
            {
                "voltage_set": voltage,
                "current_get": current_get,
                "voltage_get": voltage_get,
                "spectr": {
                    "points": spectr_points,
                    "freq": list(spectr_freq),
                },
            }
        )

except (Exception, BaseException, KeyboardInterrupt) as e:
    print(f"Exception {e}")

with open(
    f"meas_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json", "w", encoding="utf-8"
) as file:
    json.dump(data, file, indent=4, ensure_ascii=False)
