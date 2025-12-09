# Measuring SIs Block iv-curves versus Signal generator frequency

import json
import logging
import os
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Scontel.sis_block import SisBlock
from utils.functions import send_to_telegram

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

logger.setLevel(logging.INFO)


if __name__ == "__main__":
    # nrx = NRXPowerMeter(delay=0)
    rf = SignalGenerator(host="169.254.156.103", gpib=18)
    lo = SignalGenerator(host="169.254.156.103", gpib=19)
    sis1 = SisBlock(
        host="169.254.190.83",
        port=9876,
        bias_dev="DEV4",
        ctrl_dev="DEV3",
        offset_voltage=0.04e-3,
        offset_current=0,
    )
    #
    sis2 = SisBlock(
        host="169.254.190.83",
        port=9876,
        bias_dev="DEV2",
        ctrl_dev="DEV1",
        offset_voltage=-0.187e-3,
        offset_current=-1.3e-6,
    )

    # sis2 = SisBlock(
    #     host="169.254.71.6",
    #     port=9876,
    #     bias_dev="DEV4",
    #     ctrl_dev="DEV3",
    #     offset_voltage=0.01e-3,
    #     offset_current=0.05e-6,
    # )

    # sis1 = SisBlock(
    #     host="169.254.71.6",
    #     port=9876,
    #     bias_dev="DEV2",
    #     ctrl_dev="DEV1",
    #     offset_voltage=0.205e-3,
    #     offset_current=0.3e-6,
    # )

    data = []

    freqs = np.arange(220e9, 265e9, 0.5e9)
    print(freqs)
    voltages2 = [2.5e-3]
    voltages1 = [2.5e-3]

    try:
        rf.set_power(-80)
        rf.set_rf_output_state(False)
        lo.set_power(4)
        lo.set_rf_output_state(True)
        send_to_telegram("Measure 2SB LO Balance started")
        logger.info("Measure 2SB LO Balance started")
        for step_freq, freq in enumerate(freqs, 1):
            logger.info(f"[{step_freq}/{len(freqs)}] Set freq {freq/1e9:.4f} GHz")
            send_to_telegram(f"[{step_freq}/{len(freqs)}] Set freq {freq/1e9:.4f} GHz")
            lo.set_frequency(freq / 18.0)
            _data = {
                "frequency": freq,
                "voltage1": [],
                "current1": [],
                "voltage2": [],
                "current2": [],
                # "power": [],
            }
            for voltage1, voltage2 in zip(voltages1, voltages2):
                sis2.set_bias_voltage_iterative(voltage2)
                sis1.set_bias_voltage_iterative(voltage1)
                # time.sleep(0.1)
                volt2 = sis2.get_bias_voltage()
                curr2 = sis2.get_bias_current()
                volt1 = sis1.get_bias_voltage()
                curr1 = sis1.get_bias_current()
                # power = nrx.get_power()
                _data["voltage2"].append(volt2)
                _data["current2"].append(curr2)
                _data["voltage1"].append(volt1)
                _data["current1"].append(curr1)
                # _data["power"].append(power)
                logger.info(
                    f"V_2={volt2*1e3:.2f} mV; I_2={curr2*1e6:.2f} mkA; V_1={volt1*1e3:.2f} mV; I_1={curr1*1e6:.2f} mkA;  LO={freq/1e9:.1f} GHz"
                )

            data.append(_data)
    except (Exception, KeyboardInterrupt) as e:
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")
    if not os.path.exists("data/"):
        os.mkdir("data/")
    with open(
        f"data/meas_2sb_lo_balance_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
