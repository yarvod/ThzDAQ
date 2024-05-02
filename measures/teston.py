import json
import logging
import time
from datetime import datetime

import numpy as np

from api import SpectrumBlock
from api.Agilent.signal_generator import SignalGenerator
from api.Chopper import chopper_manager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def main(
    lo_freq: float,
    if_start,
    if_stop,
    if_steps,
):
    """

    :param lo_freq: LO frequency 200-300 ghz
    :return: None
    """

    signal_lo = SignalGenerator(host="169.254.156.103", gpib=18)
    signal_testone = SignalGenerator(host="169.254.156.103", gpib=19)
    spectrum = SpectrumBlock(host="169.254.75.176", port=5025, adapter="SOCKET")

    if_range = np.linspace(if_start, if_stop, if_steps)

    data = {
        "lo_freq": lo_freq,
        "hot_testone_freqs": [],
        "cold_testone_freqs": [],
        "hot_spectrums": [],
        "cold_spectrums": [],
    }
    steps = 2 * len(if_range)
    try:
        chopper_manager.chopper.align_to_hot()
        signal_lo.set_frequency(lo_freq / 18)
        for i in range(2):
            for step, freq in enumerate(if_range):
                testone_freq = lo_freq - freq
                signal_testone.set_frequency(testone_freq)
                time.sleep(1)
                spec_start_freq = freq - 0.5e9
                spec_stop_freq = freq + 0.5e9
                spectrum.set_start_frequency(spec_start_freq)
                spectrum.set_stop_frequency(spec_stop_freq)
                time.sleep(1)
                power, freqs = spectrum.get_trace_data(
                    start=spec_start_freq, stop=spec_stop_freq
                )
                if i == 0:
                    data["hot_testone_freqs"].append(testone_freq)
                elif i == 1:
                    data["cold_testone_freqs"].append(testone_freq)
                spectrum_data = {
                    "spectum_frequencies": freqs.tolist(),
                    "power": power,
                    "testone_freq": testone_freq,
                }
                if i == 0:
                    data["hot_spectrums"].append(spectrum_data)
                elif i == 1:
                    data["cold_spectrums"].append(spectrum_data)

                print(f"[{i * len(if_range) + step}/{steps}]")

            chopper_manager.chopper.path0()
            time.sleep(1)

    except (Exception, KeyboardInterrupt) as e:
        logger.error(f"Exception: {e}")
    finally:
        chopper_manager.chopper.align_to_cold()

    with open(
        f"meas_teston_lo{lo_freq/1e9}ghz_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    lo_freq = 234e9  # 262
    if_start = 2e9
    if_stop = 12e9
    if_steps = 300
    main(lo_freq, if_start, if_stop, if_steps)
