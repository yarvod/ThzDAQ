import json
import logging
import os
import sys
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from port_calibration import OnePortCalibration

from api.RohdeSchwarz import PowerSupplyHMP2030, VNABlock
from settings import SOCKET
from threads import Thread
from utils.functions import to_db

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

logger.setLevel(logging.INFO)

colors = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


class StateMeasure:
    thread_running = False
    data = {}
    data_is_saved = False


def set_radial_state(power_supply: PowerSupplyHMP2030, states):
    power_supply.set_global_output_state(False)
    for channel, enabled in enumerate(states, start=1):
        power_supply.set_output_state(channel, enabled)
    if any(states):
        power_supply.set_global_output_state(True)


def set_open(power_supply: PowerSupplyHMP2030):
    set_radial_state(power_supply, (True, False, False))


def set_short(power_supply: PowerSupplyHMP2030):
    set_radial_state(power_supply, (False, True, False))


def set_load(power_supply: PowerSupplyHMP2030):
    set_radial_state(power_supply, (True, False, True))


def set_dut(power_supply: PowerSupplyHMP2030):
    set_radial_state(power_supply, (False, False, False))


def serialize_trace(data):
    array = np.asarray(data["array"], dtype=complex)
    return {
        "freq": list(data["freq"]),
        "real": array.real.tolist(),
        "imag": array.imag.tolist(),
        "db": to_db(array).tolist(),
        "parameter": data["parameter"],
        "power": data["power"],
    }


def save_data():
    if StateMeasure.data_is_saved:
        logger.info("Data is already saved")
        return
    StateMeasure.data_is_saved = True
    os.makedirs("data", exist_ok=True)
    with open(
        f"data/meas_radial_cal_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(StateMeasure.data, file, ensure_ascii=False, indent=4)
    logger.info("Data is saved")


def closeEvent(event):
    StateMeasure.thread_running = False
    save_data()
    event.accept()


class MeasThread(Thread):
    plot_signal = pg.QtCore.Signal(dict)
    data_signal = pg.QtCore.Signal(dict)

    def measure_standard(self, name, switch_standard, power_supply, vna):
        if not StateMeasure.thread_running:
            return None

        logger.info("Switching radial to %s", name)
        switch_standard(power_supply)
        time.sleep(radial_settle_time)

        if not StateMeasure.thread_running:
            return None

        data = vna.get_data()
        if (
            not data
            or len(data.get("array", [])) != frequency_points
            or len(data.get("freq", [])) != frequency_points
        ):
            raise RuntimeError(f"VNA returned invalid data for {name}")

        trace = serialize_trace(data)
        self.plot_signal.emit(
            {
                "name": name,
                "x": np.asarray(trace["freq"]) / 1e9,
                "y": trace["db"],
            }
        )
        logger.info("Measured %s (%d points)", name, len(trace["freq"]))
        return data, trace

    def run(self):
        power_supply = None
        measured = {
            "settings": {
                "vna_power": vna_power,
                "start_frequency": start_frequency,
                "stop_frequency": stop_frequency,
                "frequency_points": frequency_points,
                "radial_settle_time": radial_settle_time,
                "s11_open": s11_open,
                "s11_short": s11_short,
                "s11_load": s11_load,
            }
        }
        try:
            power_supply = PowerSupplyHMP2030(
                host=power_supply_host,
                port=power_supply_port,
                adapter=SOCKET,
            )
            vna = VNABlock(host=vna_host, port=vna_port, adapter=SOCKET)
            vna.set_power(vna_power)
            vna.set_start_frequency(start_frequency)
            vna.set_stop_frequency(stop_frequency)
            vna.set_sweep(frequency_points)
            vna.set_average_status(False)
            vna.set_parameter("S11")
            vna.set_channel_format("COMP")

            standards = (
                ("open", set_open),
                ("short", set_short),
                ("load", set_load),
                ("dut_raw", set_dut),
            )
            raw_arrays = {}
            for name, switch_standard in standards:
                result = self.measure_standard(name, switch_standard, power_supply, vna)
                if result is None:
                    return
                raw_data, trace = result
                raw_arrays[name] = np.asarray(raw_data["array"], dtype=complex)
                measured[name] = trace
                self.data_signal.emit(measured.copy())

            calibration = OnePortCalibration(
                raw_arrays["open"],
                raw_arrays["short"],
                raw_arrays["load"],
                s11_open=s11_open,
                s11_short=s11_short,
                s11_load=s11_load,
            )
            calibration.calculate_calibration()
            calibrated_dut = calibration.calibrate_measure(raw_arrays["dut_raw"])

            calibrated_trace = {
                "freq": measured["dut_raw"]["freq"],
                "real": calibrated_dut.real.tolist(),
                "imag": calibrated_dut.imag.tolist(),
                "db": to_db(calibrated_dut).tolist(),
                "parameter": "S11 calibrated",
                "power": vna_power,
            }
            measured["dut_calibrated"] = calibrated_trace
            # Complex error coefficients need separate real and imaginary parts
            # to remain valid JSON.
            measured["calibration"] = {
                name: {
                    "real": np.asarray(values).real.tolist(),
                    "imag": np.asarray(values).imag.tolist(),
                }
                for name, values in calibration.cals.items()
            }
            self.plot_signal.emit(
                {
                    "name": "dut_calibrated",
                    "x": np.asarray(calibrated_trace["freq"]) / 1e9,
                    "y": calibrated_trace["db"],
                }
            )
            self.data_signal.emit(measured.copy())
            logger.info("One-port DUT calibration completed")
        except Exception:
            logger.exception("Radial calibration measurement failed")
        finally:
            StateMeasure.thread_running = False
            if power_supply is not None:
                try:
                    set_dut(power_supply)
                except Exception:
                    logger.exception("Failed to switch off radial power supply")


def collect_data(data):
    StateMeasure.data = data


def plot_data(plot, data):
    plot.plot(
        data["x"],
        data["y"],
        name=data["name"],
        pen=pg.mkPen(color=colors[len(plot.listDataItems()) % len(colors)], width=2),
    )


def main():
    StateMeasure.data = {}
    StateMeasure.data_is_saved = False

    app = pg.mkQApp("Radial one-port calibration")
    window = pg.GraphicsLayoutWidget(show=True)
    window.resize(1100, 700)
    window.setWindowTitle("Radial one-port S11 calibration")
    window.setBackground("w")
    pg.setConfigOptions(antialias=True)

    styles = {"color": "#413C58", "font-size": "15px"}
    plot = window.addPlot(title="Open / Short / Load / DUT S11")
    plot.setLabel("bottom", "Frequency, GHz", **styles)
    plot.setLabel("left", "Reflection level, dB", **styles)
    plot.addLegend()
    plot.showGrid(x=True, y=True)

    thread = MeasThread()
    thread.plot_signal.connect(lambda data: plot_data(plot, data))
    thread.data_signal.connect(collect_data)
    thread.finished.connect(save_data)

    StateMeasure.thread_running = True
    thread.start()
    setattr(window, "closeEvent", closeEvent)
    sys.exit(app.exec())


if __name__ == "__main__":
    # Measurement parameters
    power_supply_host = "192.168.129.100"
    power_supply_port = 5025
    vna_host = "169.254.106.189"
    vna_port = 5025
    vna_power = 0
    start_frequency = 10e6
    stop_frequency = 16e9
    frequency_points = 1000
    radial_settle_time = 1.0

    # Reflection coefficients of the calibration standards.
    s11_open = 1.0
    s11_short = -1.0
    s11_load = 0.0

    try:
        main()
    except KeyboardInterrupt:
        StateMeasure.thread_running = False
        save_data()
