# Measuring 2SB SRR

import json
import logging
import time
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.RohdeSchwarz.power_supply import PowerSupplyHMP2030
from api.Scontel.sis_block import SisBlock
from store.state import state
from utils.functions import send_to_telegram, to_w

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

    data = {"data": []}
    _data = {}

    measure_y_factor = False
    lo_frequency = 263e9
    inter_frequencies = np.arange(4e9, 12e9, 200e6)

    sis_voltage_1 = 2.4e-3
    sis_voltage_2 = 2.4e-3

    if_channels = {
        "upper": True,
        "lower": False,
    }

    side_bands = ["upper", "lower"]

    try:
        send_to_telegram("Measuring 2SB SSR started")
        logger.info("Measuring 2SB SSR started")
        lo.set_frequency(lo_frequency / 18)
        rs_power.set_output_state(2, True)  # turn on yig switch
        for side_band in side_bands:
            logger.info(f"Start measure {side_band} Side band")
            send_to_telegram(f"Start measure {side_band} Side band")
            _data = {
                "measure": "Power peak diff",
                "LO": lo_frequency,
                "side_band": side_band,
                "power_upper": [],
                "power_lower": [],
                "power_diff": [],
                "power_ratio": [],
                "if": [],
                "testone": [],
            }
            sis1.set_bias_voltage_iterative(sis_voltage_1)
            sis2.set_bias_voltage(sis_voltage_2)
            for step_freq, freq in enumerate(inter_frequencies, 1):
                test_tone_freq = (
                    lo_frequency + freq if side_band == "upper" else lo_frequency - freq
                )
                logger.info(
                    f"[{step_freq + 1}/{len(freq)}] Set TT freq {test_tone_freq/1e9:.4f}"
                )
                send_to_telegram(
                    f"[{step_freq + 1}/{len(freq)}] Set TT freq {test_tone_freq/1e9:.4f}"
                )
                test_tone.set_frequency(test_tone_freq)
                yig.set_frequency(freq)

                rs_power.set_output_state(1, if_channels["upper"])
                time.sleep(1)
                nrx.get_power()
                power_upper = nrx.get_power()

                rs_power.set_output_state(1, if_channels["lower"])
                time.sleep(1)
                nrx.get_power()
                power_lower = nrx.get_power()

                _data["power_upper"].append(power_upper)
                _data["power_lower"].append(power_lower)
                if side_band == "upper":
                    power_diff = power_upper - power_lower
                    power_ratio = to_w(power_upper) / to_w(power_lower)
                else:
                    power_diff = power_lower - power_upper
                    power_ratio = to_w(power_lower) / to_w(power_upper)
                logger.info(f"Power diff {power_diff:.4f} dBm")
                _data["power_diff"].append(power_diff)
                _data["if"].append(freq)
                _data["testone"].append(test_tone_freq)
                _data["power_ratio"].append(power_ratio)

            data["data"].append(_data)

        if measure_y_factor:
            chopper_manager.chopper.align_to_cold()
            _data = {
                "measure": "Y factor",
                "p_upper_hot": [],
                "p_upper_cold": [],
                "p_lower_hot": [],
                "p_lower_cold": [],
            }
            logger.info("Start measuring Y-factor")
            test_tone.set_rf_output_state(False)
            for side_band in side_bands:
                rs_power.set_output_state(1, if_channels[side_band])
                for chopper_state in ["cold", "hot"]:
                    logger.info(f"Channel {side_band} Load {chopper_state}")
                    rotate = getattr(
                        chopper_manager.chopper, f"align_to_{chopper_state}"
                    )
                    rotate()
                    for freq in inter_frequencies:
                        yig.set_frequency(freq)
                        time.sleep(0.05)
                        power = nrx.get_power()
                        _data[f"p_{side_band}_{chopper_state}"].append(power)

    except (Exception, KeyboardInterrupt) as e:
        data["data"].append(_data)
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")

    with open(
        f"data/meas_2sb_srr_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
