# Измерение тока накачки в зависимости от диапазона и мощности VNA

import json
import logging
import time
from datetime import datetime

import numpy as np

from api import VNABlock
from api.Scontel.sis_block import SisBlock
from utils.functions import send_to_telegram
from utils.logger import configure_logger

configure_logger()
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    vna = VNABlock()
    sis = SisBlock(
        host="169.254.190.83",
        port=9876,
        bias_dev="DEV2",
        ctrl_dev="DEV1",
    )
    sis.connect()
    if_ranges = [
        [0.01e9, 2e9, 1000],
        [2e9, 4e9, 1000],
        [4e9, 6e9, 1000],
        [6e9, 8e9, 1000],
        [8e9, 10e9, 1000],
        [10e9, 12e9, 1000],
    ]

    power_ranges = np.arange(-55, -19, 1)

    voltages = np.linspace(2.5e-3, 3.2e-3, 50)

    data = {
        "data": [],
    }

    try:
        send_to_telegram("New measurement started: Vna power sis current test pumping")

        for ind_power, power in enumerate(power_ranges, 1):
            _data = {
                "power": float(power),
                "data": [],
            }
            vna.set_power(power)
            logger.info(f"[step {ind_power}/{len(power_ranges)} Set power {power} dBm]")
            send_to_telegram(
                f"[step {ind_power}/{len(power_ranges)} Set power {power}] dBm"
            )

            for ind_range, if_range in enumerate(if_ranges, 1):
                __data = {
                    "start_frequency": if_range[0],
                    "stop_frequency": if_range[1],
                    "points_frequency": if_range[2],
                    "voltages": [],
                    "currents": [],
                }
                vna.set_parameter("S21")
                vna.set_start_frequency(if_range[0])
                vna.set_stop_frequency(if_range[1])
                vna.set_sweep(if_range[2])
                vna.set_channel_format("COMP")
                vna.set_average_status(True)
                vna.set_average_count(10)
                time.sleep(5)

                logger.info(
                    f"[Range {if_range[0]/1e9:.1f}-{if_range[1]/1e9:.1f} GHz start scan bias"
                )

                for voltage in voltages:
                    sis.set_bias_voltage(voltage)
                    time.sleep(0.1)
                    __data["voltages"].append(sis.get_bias_voltage())
                    __data["currents"].append(sis.get_bias_current())

                _data["data"].append(__data)

            data["data"].append(_data)

    except (Exception, KeyboardInterrupt) as e:
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")

    with open(
        f"data/meas_vna_sis_current_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
