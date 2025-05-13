# Measuring SIs Block iv-curves versus Signal generator frequency

import json
import logging
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
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
    # nrx = NRXPowerMeter(delay=0)
    sg = SignalGenerator(host=state.PROLOGIX_IP, gpib=19)
    sis2 = SisBlock(
        host=state.BLOCK_ADDRESS,
        port=state.BLOCK_PORT,
        bias_dev="DEV2",
        ctrl_dev="DEV4",
        offset_voltage=-0.187e-3,
        offset_current=-1.3e-6,
    )

    sis1 = SisBlock(
        host=state.BLOCK_ADDRESS,
        port=state.BLOCK_PORT,
        bias_dev="DEV4",
        ctrl_dev="DEV1",
        offset_voltage=0.04e-3,
        offset_current=0,
    )

    data = []
    npoints = 301

    freqs = np.arange(12.2, 14.72, 0.014)
    freqs = 18e9 * freqs
    print(freqs)
    voltages2 = np.linspace(-5e-3, 5e-3, npoints)
    voltages1 = np.linspace(-25e-3, 25e-3, npoints)

    try:
        send_to_telegram("Measure 2SB LO Balance started")
        logger.info("Measure 2SB LO Balance started")
        for step_freq, freq in enumerate(freqs, 1):
            logger.info(f"[{step_freq}/{len(freqs)}] Set freq {freq:.4f}")
            send_to_telegram(f"[{step_freq}/{len(freqs)}] Set freq {freq:.4f}")
            sg.set_frequency(freq / 18.0)
            _data = {
                "frequency": freq,
                "voltage1": [],
                "current1": [],
                "voltage2": [],
                "current2": [],
                # "power": [],
            }
            for i, voltage2 in enumerate(voltages2):
                voltage1 = voltages1[i]
                sis2.set_bias_voltage(voltage2)
                sis1.set_bias_voltage(voltage1)
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

    with open(
        f"data/meas_2sb_lo_balance_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
