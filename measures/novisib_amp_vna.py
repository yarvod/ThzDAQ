# Проверка S параметров усилка Новосибирска при разных напряжеиях смещения

import json
import logging
import time
from datetime import datetime

import numpy as np

import settings
from api import PowerSupply, VNABlock, TemperatureController
from utils.functions import send_to_telegram

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def wait_temperature(diff=0.01):
    min_max = 20
    step = 1
    while min_max >= diff:
        logger.info(f"[wait_temperature] Step {step} starting")
        send_to_telegram(f"[wait_temperature] Step {step} starting")
        temperatures = []
        for i in range(120):
            temp = temp_contr.get_temperature_a()
            temperatures.append(temp)
            time.sleep(0.7)

        temperatures = np.array(temperatures)
        min_max = np.max(temperatures) - np.min(temperatures)
        logger.info(f"[wait_temperature] Step {step}; min_max = {min_max:.5}")
        send_to_telegram(f"[wait_temperature] Step {step}; min_max = {min_max:.5}")
        step += 1


if __name__ == "__main__":

    keithley = PowerSupply()
    vna = VNABlock()
    temp_contr = TemperatureController(
        port=1234, host="169.254.156.101", gpib=12, adapter=settings.PROLOGIX_ETHERNET
    )

    voltages = [
        1.5,
        1.6,
        1.7,
        1.8,
        1.9,
        2.0,
        2.1,
        2.2,
        2.3,
    ]

    vna_params = ["s11", "s22", "s12", "s21"]

    data = {
        "parameters": {
            "vna": {
                "start_freq": 0.01e9,
                "stop_freq": 16e9,
                "sweep": 1000,
                "average_count": 10,
                "average_status": True,
                "power": -50,
            }
        },
        "data": [],
    }

    try:
        send_to_telegram("New measurement started: Novosib amp vna test")
        keithley.set_voltage(0)
        keithley.set_current(0.02)
        keithley.set_output_state(1)
        vna.set_power(data["parameters"]["vna"]["power"])
        vna.set_start_frequency(data["parameters"]["vna"]["start_freq"])
        vna.set_stop_frequency(data["parameters"]["vna"]["stop_freq"])
        vna.set_sweep(data["parameters"]["vna"]["sweep"])
        vna.set_channel_format("COMP")
        vna.set_average_status(data["parameters"]["vna"]["average_status"])
        vna.set_average_count(data["parameters"]["vna"]["average_count"])

        for ind, voltage in enumerate(voltages, 1):
            _data = {
                "voltage": None,
                "current": None,
                "temperature": None,
            }
            logger.info(f"[step {ind}/{len(voltages)} Set voltage {voltage}]")
            send_to_telegram(f"[step {ind}/{len(voltages)} Set voltage {voltage}]")
            keithley.set_voltage(voltage)
            wait_temperature(0.02)
            _data["current"] = keithley.get_current()
            _data["voltage"] = keithley.get_voltage()
            _data["temperature"] = temp_contr.get_temperature_b()

            for vna_param in vna_params:
                vna.set_parameter(vna_param.upper())
                vna.set_channel_format("COMP")
                for _ in range(4):
                    vna.get_data()
                    time.sleep(2)
                vna_data = vna.get_data()
                vna_data.pop("array")
                vna_data.pop("freq")
                _data[vna_param] = vna_data

            data["data"].append(_data)

    except (Exception, KeyboardInterrupt) as e:
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")
        keithley.set_voltage(0)
        keithley.set_output_state(0)

    keithley.set_voltage(0)
    keithley.set_output_state(0)

    with open(
        f"data/meas_amp_vna_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
