# Measuring 2SB IF balance

import json
import logging
import time
from datetime import datetime

import numpy as np

from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.RohdeSchwarz.power_supply import PowerSupplyHMP2030
from api.Scontel.sis_block import SisBlock
from store.state import state
from utils.functions import send_to_telegram

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

logger.setLevel(logging.INFO)


if __name__ == "__main__":
    nrx = NRXPowerMeter(delay=0)
    yig = NiYIGManager(host=state.NI_IP)
    rs_power = PowerSupplyHMP2030(host="169.254.0.30", port=5025)
    sis2 = SisBlock(
        host="169.254.190.83",
        port=9876,
        bias_dev="DEV2",
        ctrl_dev="DEV4",
        offset_voltage=-0.187e-3,
        offset_current=-1.3e-6,
    )

    sis1 = SisBlock(
        host="169.254.190.83",
        port=9876,
        bias_dev="DEV4",
        ctrl_dev="DEV1",
        offset_voltage=0.04e-3,
        offset_current=0,
    )

    sis2.connect()
    sis1.connect()

    inter_frequencies = np.arange(3e9, 7.8e9, 20e6)

    sis_voltage_1 = 4.2e-3
    sis_voltage_2 = 4.8e-3

    voltages_1 = [sis_voltage_1, sis_voltage_1, sis_voltage_2, sis_voltage_2]
    voltages_2 = [sis_voltage_1, sis_voltage_2, sis_voltage_1, sis_voltage_2]

    data = {"if": inter_frequencies.tolist(), "data": []}
    _data = {}

    try:
        send_to_telegram("Measuring 2SB IF balance started")
        logger.info("Measuring 2SB IF balance started")
        for bs1, bs2 in zip(voltages_1, voltages_2):
            logger.info(f"SIS1 voltage {bs1*1e3:.2f}mV; SIS2 voltage {bs2*1e3:.2f}mV;")
            send_to_telegram(
                f"SIS1 voltage {bs1*1e3:.2f}mV; SIS2 voltage {bs2*1e3:.2f}mV;"
            )
            sis1.set_bias_voltage_iterative(bs1)
            sis2.set_bias_voltage(bs2)
            _data = {
                "sis1_voltage": bs1,
                "sis1_current": sis1.get_bias_current(),
                "sis2_voltage": bs2,
                "sis2_current": sis2.get_bias_current(),
                "power_ch1": [],
                "power_ch2": [],
            }
            for channel in ["ch1", "ch2"]:
                rs_power.set_output_state(1, channel == "ch2")
                time.sleep(1)
                logger.info(f"Start measure channel {channel}")
                send_to_telegram(f"Start measure channel {channel}")
                time.sleep(1)
                for freq in inter_frequencies:
                    yig.set_frequency(freq)
                    time.sleep(0.1)
                    _data[f"power_{channel}"].append(nrx.get_power())

            data["data"].append(_data)
    except (Exception, KeyboardInterrupt) as e:
        data["data"].append(_data)
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")

    with open(
        f"data/meas_2sb_if_balance_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
