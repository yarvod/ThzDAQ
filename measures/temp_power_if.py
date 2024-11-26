import json
import logging
import time
from datetime import datetime

import numpy as np

import settings
from api import PowerSupply, TemperatureController
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from store.state import state
from utils.functions import linear, send_to_telegram

logger = logging.getLogger(__name__)

nrx = NRXPowerMeter(delay=0, aperture_time=50)
ni_yig = NiYIGManager(host=state.NI_IP)
keithley = PowerSupply()
temp_contr = TemperatureController(
    port=1234, host="169.254.156.101", gpib=12, adapter=settings.PROLOGIX_ETHERNET
)

resistor_voltages = [
    0,
    0.4,
    0.8,
    1.2,
    1.6,
    2,
    2.4,
    2,
    1.6,
    1.2,
    0.8,
    0.4,
    0,
]
freqs = np.linspace(3, 13, 300)
data = []


def wait_temperature(diff=0.01):
    min_max = 20
    step = 1
    while min_max >= diff:
        logger.info(f"[wait_temperature] Step {step} starting")
        send_to_telegram(f"[wait_temperature] Step {step} starting")
        temperatures = []
        for i in range(120):
            temp_b = temp_contr.get_temperature_b()
            temperatures.append(temp_b)
            time.sleep(0.7)

        temperatures = np.array(temperatures)
        min_max = np.max(temperatures) - np.min(temperatures)
        logger.info(f"[wait_temperature] Step {step}; min_max = {min_max}")
        send_to_telegram(f"[wait_temperature] Step {step}; min_max = {min_max:.5}")
        step += 1


try:
    send_to_telegram(f"New measure starting!")
    keithley.set_current(0.035)
    keithley.set_voltage(0)
    keithley.set_output_state(1)
    for voltage in resistor_voltages:
        keithley.set_voltage(voltage)
        logger.info(f"Set resistor Voltage {voltage}")
        send_to_telegram(f"Set resistor Voltage {voltage}")
        wait_temperature()
        send_to_telegram(
            f"Finished temperature stabilization {temp_contr.get_temperature_b():.3}"
        )
        dat = {
            "temperature": temp_contr.get_temperature_b(),
            "power": [],
            "freq": [],
        }

        for freq in freqs:
            value = int(
                linear(
                    freq * 1e9,
                    *state.CALIBRATION_DIGITAL_FREQ_2_POINT,
                )
            )
            resp = ni_yig.write_task(value=value)
            resp_int = resp.get("result", None)
            if resp_int is None:
                continue
            else:
                _freq = round(
                    linear(resp_int, *state.CALIBRATION_DIGITAL_POINT_2_FREQ) * 1e-9,
                    2,
                )
            dat["power"].append(nrx.get_power())
            dat["freq"].append(_freq)
        send_to_telegram(f"Finished yig scan for resistor voltage {voltage}")

        data.append(dat)
except (Exception, KeyboardInterrupt) as e:
    logger.error(f"Exception: {e}")
    send_to_telegram(f"Exception: {e}")
    keithley.set_current(0.035)
    keithley.set_voltage(0)
    keithley.set_output_state(0)

with open(
    f"meas_temp_power_if_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

send_to_telegram(f"Measurement successfully finished!")
