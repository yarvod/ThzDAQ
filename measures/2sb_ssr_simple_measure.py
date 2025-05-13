# Measuring 2SB SSR

import json
import logging
import time
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
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
    lo = SignalGenerator(host=state.PROLOGIX_IP, gpib=19)
    test_tone = SignalGenerator(host=state.PROLOGIX_IP, gpib=18)
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

    data = []
    _data = {}

    lo_frequency = 263e9
    inter_frequencies = np.arange(3e9, 7.8e9, 20e6)

    sis_voltage_1 = 2.4e-3
    sis_voltage_2 = 2.4e-3

    side_bands = ["upper", "lower"]

    try:
        send_to_telegram("Measuring 2SB SSR started")
        logger.info("Measuring 2SB SSR started")
        lo.set_frequency(lo_frequency / 18)
        for side_band in side_bands:
            logger.info(f"Start measure {side_band} Side band")
            send_to_telegram(f"Start measure {side_band} Side band")
            _data = {
                "LO": lo_frequency,
                "side_band": side_band,
                "power_ch1": [],
                "power_ch2": [],
                "power_diff": [],
                "powers_ch1": [],
                "powers_ch2": [],
                "if": [],
                "testone": [],
            }
            sis1.set_bias_voltage_iterative(sis_voltage_1)
            sis2.set_bias_voltage(sis_voltage_2)
            for step_freq, freq in enumerate(inter_frequencies, 1):
                test_tone_freq = (
                    lo_frequency + freq if side_band == "upper" else lo_frequency - freq
                )
                logger.info(f"Set TT freq {test_tone_freq/1e9:.4f}")
                send_to_telegram(f"Set TT freq {test_tone_freq/1e9:.4f}")
                test_tone.set_frequency(test_tone_freq)
                yig.set_frequency(freq)
                rs_power.set_output_state(1, True)
                time.sleep(1)
                powers_ch1 = []
                powers_ch2 = []
                for _if in np.linspace(freq - 30e6, freq + 30e6, 10):
                    yig.set_frequency(_if)
                    time.sleep(0.1)
                    powers_ch1.append(nrx.get_power())
                rs_power.set_output_state(1, False)
                time.sleep(1)
                for _if in np.linspace(freq - 30e6, freq + 30e6, 10):
                    yig.set_frequency(_if)
                    time.sleep(0.1)
                    powers_ch2.append(nrx.get_power())
                power_ch1 = np.max(powers_ch1)
                power_ch2 = np.max(powers_ch2)
                _data["power_ch1"].append(power_ch1)
                _data["power_ch2"].append(power_ch2)
                _data["powers_ch1"].append(powers_ch1)
                _data["powers_ch2"].append(powers_ch2)
                power_diff = (
                    power_ch1 - power_ch2
                    if side_band == "upper"
                    else power_ch2 - power_ch1
                )
                logger.info(f"Power diff {power_diff:.4f} dBm")
                _data["power_diff"].append(power_diff)
                _data["if"].append(freq)
                _data["testone"].append(test_tone_freq)

            data.append(_data)
    except (Exception, KeyboardInterrupt) as e:
        data.append(_data)
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")

    with open(
        f"data/meas_2sb_srr_simple_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
