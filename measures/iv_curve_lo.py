# Measuring SIs Block iv-curves versus Signal generator frequency

import json
import logging
from datetime import datetime

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
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
    sg = SignalGenerator(host=state.PROLOGIX_IP, gpib=18)
    sis = SisBlock(
        host=state.BLOCK_ADDRESS,
        port=state.BLOCK_PORT,
        bias_dev="DEV2",
        ctrl_dev="DEV1",
    )
    sis.connect()
    data = []
    freqs = np.arange(232.2e9, 232e9, 1e9)
    voltages = np.linspace(-5e-3, 5e-3, 301)

    try:
        send_to_telegram(
            "Measure SIs Block iv-curves versus Signal generator frequency started"
        )
        logger.info(
            "Measure SIs Block iv-curves versus Signal generator frequency started"
        )
        for step_freq, freq in enumerate(freqs, 1):
            logger.info(f"[{step_freq}/{len(freqs)}] Set freq {freq:.4f}")
            send_to_telegram(f"[{step_freq}/{len(freqs)}] Set freq {freq:.4f}")
            sg.set_frequency(freq)
            _data = {
                "frequency": freq,
                "voltage": [],
                "current": [],
                "power": [],
            }
            for voltage in voltages:

                sis.set_bias_voltage(voltage)
                volt = sis.get_bias_voltage()
                curr = sis.get_bias_current()
                power = nrx.get_power()
                _data["voltage"].append(volt)
                _data["current"].append(curr)
                _data["power"].append(power)
                logger.info(
                    f"V={volt*1e3:.2f} mV; I={curr*1e6:.2f} mkA; P={power:.2f} dBm; LO={freq/1e9:.1f} GHz"
                )

            data.append(_data)
    except (Exception, KeyboardInterrupt) as e:
        logger.error(f"Exception: {e}")
        send_to_telegram(f"Exception: {e}")

    with open(
        f"data/meas_iv-lo_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    send_to_telegram(f"Measurement successfully finished!")
