# Measuring SIs Block current versus Signal generator frequency

import json

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Scontel.sis_block import SisBlock
from store.state import state

sg = SignalGenerator(host=state.PROLOGIX_IP)
sis = SisBlock(
    host=state.BLOCK_ADDRESS,
    port=state.BLOCK_PORT,
    bias_dev=state.BLOCK_BIAS_DEV,
    ctrl_dev=state.BLOCK_CTRL_DEV,
)
sis.connect()
results = {
    "freq": [],
    "volt": [],
    "curr": [],
}
freqs = np.linspace(220e9, 325e9, 501)
for freq in freqs:
    sg.set_frequency(freq)
    sis.set_bias_voltage(5 * 1e-3)
    volt = sis.get_bias_voltage()
    curr = sis.get_bias_current()

    results["freq"].append(freq)
    results["volt"].append(volt)
    results["curr"].append(curr)
    print(f"freq {freq / 1e9}")

with open("meas4.json", "w", encoding="utf-8") as file:
    json.dump(results, file, ensure_ascii=False, indent=4)
