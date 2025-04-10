import logging
import time
import json
from datetime import datetime

import numpy as np

from api import SpectrumBlock
from api.Agilent.signal_generator import SignalGenerator
from api.Arduino.grid import GridManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.Scontel.sis_block import SisBlock
from store.state import state
from utils.logger import configure_logger

configure_logger()
logger = logging.getLogger(__name__)

sis = SisBlock(
    host=state.BLOCK_ADDRESS,
    port=state.BLOCK_PORT,
    bias_dev="DEV2",
    ctrl_dev="DEV1",
)
sis.connect()
nrx = NRXPowerMeter(delay=0, aperture_time=50)
spectrum = SpectrumBlock(host="169.254.156.101", port=1234, gpib=20, delay=0.2)
grid = GridManager()
sg = SignalGenerator(host="169.254.156.103", port=1234, gpib=18)

spectrum.set_span_frequency(10e6)
spectrum.peak_search()
spectrum.get_peak_power()
spectrum.get_peak_power()
spectrum.get_peak_power()


if_range = np.arange(3.5e9, 5.5e9, 0.5e9)
grid_angles = np.arange(0, 15, 0.25)
voltage_range = np.arange(1.8e-3, 3.1e-3, 0.1e-3)


def save_data(data_to_save, name=""):
    with open(
        f"meas_if_spectr_testone_{name}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=4)


data = {
    "if": 0,
    "angle": [],
    "bias_data": [],
}


try:
    for if_value in if_range:
        data = {
            "if": if_value,
            "angle": [],
            "bias_data": [],
        }
        grid.rotate(0)
        sg.set_frequency(252e9 + if_value)
        logger.info(f"Set IF {if_value/1e9:.2f} GHz")
        center_freqs = [if_value, if_value * 2, if_value * 3]
        for angle in grid_angles:
            logger.info(f"Angle {angle}")
            grid.rotate(angle)
            bias_data = {
                "sis_voltage": [],
                "sis_current": [],
                "power_meter": [],
                "peaks": [],
            }
            for voltage in voltage_range:
                sis.set_bias_voltage(voltage)

                peaks = []
                for cf in center_freqs:
                    spectrum.set_center_frequency(cf)
                    time.sleep(0.5)
                    peak = []
                    attempt = 1
                    attempts = 10
                    step = 0
                    steps = 3
                    while attempt <= attempts:
                        try:
                            spectrum.peak_search()
                            spectrum.peak_search()
                            spectrum.get_peak_power()
                            pk = spectrum.get_peak_power()
                            peak.append(pk)
                            step += 1
                            if step >= steps:
                                break
                        except Exception:
                            ...
                        time.sleep(0.1)
                        attempt += 1
                    if attempt == attempts:
                        logger.error(f"Unable to get data for angle {angle}")
                        continue
                    peak_mean = np.mean(peak)
                    logger.info(f"CF {cf/1e9:.2f} GHz Peaks: {peak}; Mean: {peak_mean}")
                    peaks.append(peak_mean)

                sis_current = sis.get_bias_current()
                sis_voltage = sis.get_bias_voltage()
                power_meter = nrx.get_power()

                bias_data["sis_current"].append(sis_current)
                bias_data["sis_voltage"].append(voltage)
                bias_data["power_meter"].append(power_meter)
                bias_data["peaks"].append(peaks)

            data["bias_data"].append(bias_data)

        save_data(data, f"if{if_value/1e9:.2f}ghz")

except (Exception, KeyboardInterrupt) as e:
    logger.exception(f"{e}", exc_info=True)

finally:
    save_data(data, "last")

grid.rotate(0)
