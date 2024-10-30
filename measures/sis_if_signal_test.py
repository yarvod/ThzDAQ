import json
import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Scontel.sis_block import SisBlock
from store.state import state
from utils.functions import send_to_telegram

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def set_sis_voltage(
    sis_block, desired_voltage, tolerance=0.001, max_iterations=500
) -> Optional[float]:
    voltage_to_set = desired_voltage
    iteration = 0

    while iteration < max_iterations:
        sis_block.set_bias_voltage(voltage_to_set)
        time.sleep(1)
        real_voltage = sis_block.get_bias_voltage()
        logger.info(f"Real voltage {real_voltage}")

        if abs(real_voltage - desired_voltage) <= tolerance * abs(desired_voltage):
            logger.info(
                f"Желаемое напряжение {desired_voltage} достигнуто с точностью {tolerance * 100:.2}%. за {iteration} итераций"
            )
            send_to_telegram(
                f"Желаемое напряжение {desired_voltage} достигнуто с точностью {tolerance * 100:.2}%. за {iteration} итераций"
            )
            return real_voltage

        voltage_to_set += desired_voltage - real_voltage
        logger.info(f"Voltage to set {voltage_to_set}")
        iteration += 1

    logger.error(
        f"Не удалось достичь желаемого напряжения {desired_voltage} за {max_iterations} итераций."
    )
    send_to_telegram(
        f"Не удалось достичь желаемого напряжения {desired_voltage} за {max_iterations} итераций."
    )
    return None


if __name__ == "__main__":
    signal = SignalGenerator(host="169.254.156.103", gpib=19)
    signal.set_rf_output_state(True)
    sis = SisBlock(
        host=state.BLOCK_ADDRESS,
        port=state.BLOCK_PORT,
        bias_dev=state.BLOCK_BIAS_DEV,
        ctrl_dev=state.BLOCK_CTRL_DEV,
    )
    sis.connect()

    voltage = 2.8e-3
    powers = np.linspace(-60, -15, 5)
    freqs = np.linspace(3e9, 12e9, 100)

    data = []

    try:
        send_to_telegram(f"New measurement SIS IF signal test!")
        for power in powers:
            _data = {
                "power": power,
                "freqs": [],
                "voltages": [],
                "currents": [],
            }
            signal.set_power(power)
            send_to_telegram(f"Set power {power:.3} dBm")
            status = set_sis_voltage(sis, voltage, tolerance=0.0005)

            if not status:
                break

            for freq in freqs:
                signal.set_frequency(freq)
                logger.info(f"Set freg {round(freq, 2)} for power {round(power, 1)}dBm")
                send_to_telegram(
                    f"Set freg {round(freq, 2)} for power {round(power, 1)}dBm"
                )
                time.sleep(1)
                set_sis_voltage(sis, voltage, tolerance=0.0005)
                _data["freqs"].append(freq)
                _data["voltages"].append(sis.get_bias_voltage())
                _data["currents"].append(sis.get_bias_current())

            data.append(_data)

    except (Exception, KeyboardInterrupt) as e:
        logger.exception(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")
        signal.set_amplitude(-80)
        signal.set_rf_output_state(False)
        sis.set_bias_voltage(0)

    signal.set_amplitude(-80)
    signal.set_rf_output_state(False)
    sis.set_bias_voltage(0)

    with open(
        f"meas_sis_if_signal_test_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
