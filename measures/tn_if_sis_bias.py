"""
Измерение Шумовой температуры от ПЧ для разных напряжениях СИС смесителя
"""

import json
import logging
import time
from datetime import datetime

import numpy as np

from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.Scontel.sis_block import SisBlock
from store.state import state
from utils.functions import send_to_telegram, get_if_tn
from utils.logger import configure_logger

configure_logger()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


if __name__ == "__main__":
    sis = SisBlock(
        host=state.BLOCK_ADDRESS,
        port=state.BLOCK_PORT,
        bias_dev="DEV2",
        ctrl_dev="DEV1",
    )
    sis.connect()
    ni_yig = NiYIGManager(host=state.NI_IP)
    nrx = NRXPowerMeter(delay=0, aperture_time=50)

    voltages_range = np.arange(2.1, 3.2, 0.05) * 1e-3
    freq_range = np.linspace(3, 13, 300) * 1e9

    data = {
        "type": "Tn(IF) for different SIS bias voltages",
        "t_hot": 300,
        "t_cold": 77,
        "frequency": freq_range.tolist(),
        "data": [],
    }

    try:
        chopper_manager.chopper.align_to_cold()
        for voltage_step, voltage in enumerate(voltages_range, 1):
            logger.info(f"Start for voltage = {voltage*1e3:.3f}")
            send_to_telegram(f"Start for voltage = {voltage*1e3:.3f}")

            _data = {
                "voltage": voltage,
                "hot_power": [],
                "cold_power": [],
                "y_factor": [],
                "tn": [],
            }
            # HOT
            logger.info("Hot measure...")
            chopper_manager.chopper.path0()
            time.sleep(2)
            sis.set_bias_voltage_iterative(voltage)
            for freq_step, freq in enumerate(freq_range, 1):
                ni_yig.set_frequency(freq)
                time.sleep(0.1)
                power = nrx.get_power()
                _data["hot_power"].append(power)

            # COLD
            logger.info("Cold measure...")
            chopper_manager.chopper.path0()
            time.sleep(2)
            sis.set_bias_voltage_iterative(voltage)
            for freq_step, freq in enumerate(freq_range, 1):
                ni_yig.set_frequency(freq)
                time.sleep(0.1)
                power = nrx.get_power()
                _data["cold_power"].append(power)

            _data["y_factor"] = (
                np.array(_data["hot_power"]) - np.array(_data["cold_power"])
            ).tolist()
            _data["tn"] = get_if_tn(
                _data["hot_power"],
                _data["cold_power"],
                th=data["t_hot"],
                tc=data["t_cold"],
            ).tolist()
            data["data"].append(_data)

    except (Exception, KeyboardInterrupt) as e:
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")
        sis.set_bias_voltage(0)
        chopper_manager.chopper.align_to_cold()
    try:
        with open(
            f"measures/data/meas_tn_if_sis_bias_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    except (FileNotFoundError, Exception):
        with open(
            f"meas_tn_if_sis_bias_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
