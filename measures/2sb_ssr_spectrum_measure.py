# Measuring 2SB SSR

import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg

from api import SpectrumBlock
from api.Agilent.signal_generator import SignalGenerator
from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.RohdeSchwarz.power_supply import PowerSupplyHMP2030
from api.Scontel.sis_block import SisBlock
from threads import Thread
from utils.functions import send_to_telegram

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


class MeasThread(Thread):
    plot_signal = pg.QtCore.Signal(dict)
    plot2_signal = pg.QtCore.Signal(dict)
    data_signal = pg.QtCore.Signal(dict)

    def run(self):
        nrx = NRXPowerMeter(host="169.254.2.20", delay=0)
        lo = SignalGenerator(host="169.254.156.103", gpib=19)
        test_tone = SignalGenerator(host="169.254.156.103", gpib=18)
        yig = NiYIGManager(host="169.254.0.86")
        spectrum = SpectrumBlock(
            host="169.254.156.103",
            port=1234,
            gpib=20,
            adapter="PROLOGIX ETHERNET",
            delay=0.01,
        )
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

        data = {"upper": {}, "lower": {}, "y_factor": {}}
        _data = {}

        try:
            send_to_telegram("Measuring 2SB SSR started")
            logger.info("Measuring 2SB SSR started")

            test_tone.set_rf_output_state(True)
            lo.set_rf_output_state(True)
            lo.set_frequency(lo_frequency / 18)

            spectrum.set_single_sweep_mode()
            spectrum.set_video_bw(20)
            spectrum.set_resolution_bw(200)
            spectrum.set_span_frequency(100e3)

            rs_power.set_output_state(2, False)  # turn off YIG

            if measure_y_factor:
                chopper_manager.chopper.align_to_hot()

            for side_band in side_bands:
                if not StateMeasure.thread_running:
                    break
                logger.info(f"Start measure {side_band} Side band")
                send_to_telegram(f"Start measure {side_band} Side band")
                _data = {
                    "LO": lo_frequency,
                    "side_band": side_band,
                    "power_upper": [],
                    "power_lower": [],
                    "power_diff": [],
                    "if": [],
                }
                sis1.set_bias_voltage_iterative(sis_voltage_1)
                sis2.set_bias_voltage(sis_voltage_2)
                for step_freq, freq_range in enumerate(inter_frequencies_reshaped, 1):
                    if not StateMeasure.thread_running:
                        break

                    for if_channel in if_channels.keys():
                        rs_power.set_output_state(1, if_channels[if_channel])
                        time.sleep(1)
                        for fi, freq in enumerate(freq_range):
                            test_tone_freq = (
                                lo_frequency + freq
                                if side_band == "upper"
                                else lo_frequency - freq
                            )
                            test_tone.set_frequency(test_tone_freq)
                            spectrum.set_center_frequency(freq)
                            if fi == 0:
                                time.sleep(2)
                            else:
                                time.sleep(0.1)

                            spectrum.trigger()
                            spectrum.trigger()
                            spectrum.trigger()
                            time.sleep(0.05)
                            spectrum.get_peak_power()
                            spectrum.get_peak_power()
                            spectrum.get_peak_power()
                            spectrum.get_peak_power()
                            spectrum.get_peak_power()

                            powers = []
                            for i in range(5):
                                spectrum.peak_search()
                                p = spectrum.get_peak_power()
                                powers.append(p)
                                logger.info(
                                    f"Points to average {if_channel} IF {freq} Power {p:.4f} dBm"
                                )
                                time.sleep(0.01)
                            power = np.mean(powers)
                            _data[f"power_{if_channel}"].append(power)
                            logger.info(
                                f"TT freq {test_tone_freq / 1e9:.4f} power mean {power:.4f} dBm"
                            )
                            send_to_telegram(
                                f"TT freq {test_tone_freq / 1e9:.4f} power {power:.4f} dBm"
                            )

                    power_diff = (
                        np.array(_data["power_upper"])[-one_range_len:]
                        - np.array(_data["power_lower"])[-one_range_len:]
                        if side_band == "upper"
                        else np.array(_data["power_lower"])[-one_range_len:]
                        - np.array(_data["power_upper"])[-one_range_len:]
                    ).tolist()
                    logger.info(f"Power diff {power_diff} dBm")
                    _data["power_diff"].extend(power_diff)
                    _data["if"].extend(freq_range.tolist())
                    self.plot_signal.emit(
                        {
                            "new_plot": step_freq == 1,
                            "legend_postfix": side_band,
                            "x": freq_range / 1e9,
                            "y": power_diff,
                        }
                    )

                    data[side_band] = _data
                    self.data_signal.emit(data)

            if measure_y_factor:
                chopper_manager.chopper.align_to_cold()
                rs_power.set_output_state(2, True)  # turn on YIG
                data["y_factor"] = {
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
                        for fi, freq in enumerate(inter_frequencies):
                            yig.set_frequency(freq)
                            time.sleep(0.05)
                            power = nrx.get_power()
                            data["y_factor"][f"p_{side_band}_{chopper_state}"].append(
                                power
                            )
                            self.data_signal.emit(data)
                            self.plot2_signal.emit(
                                {
                                    "new_plot": fi == 0,
                                    "legend_postfix": f"{side_band} {chopper_state}",
                                    "x": [freq / 1e9],
                                    "y": [power],
                                }
                            )

                    self.plot2_signal.emit(
                        {
                            "new_plot": True,
                            "legend_postfix": f"{side_band} Y-factor",
                            "x": inter_frequencies / 1e9,
                            "y": np.array(data["y_factor"][f"p_{side_band}_hot"])
                            - np.array(data["y_factor"][f"p_{side_band}_cold"]),
                        }
                    )

                chopper_manager.chopper.align_to_cold()
                rs_power.set_output_state(2, False)  # turn off YIG

            self.finished.emit()
        except (Exception, KeyboardInterrupt) as e:
            StateMeasure.thread_running = False
            self.data_signal.emit(data)
            logger.error(f"Exception: {e}")
            send_to_telegram(f"Exception: {e}")
            self.finished.emit()

        send_to_telegram(f"Measurement successfully finished!")
        self.finished.emit()


def get_plot_items(plot_widget):
    return {item.name(): item for item in plot_widget.items}


def get_plot_number(name: str):
    val = next((_ for _ in re.findall(r"№ (\d+);", name)), 0)
    return int(val)


def collect_data(data):
    StateMeasure.data = data


def save_data():
    if StateMeasure.data_is_saved:
        logger.info("Data is already saved")
        return
    StateMeasure.data_is_saved = True
    if not os.path.exists("data/"):
        os.mkdir("data/")
    with open(
        f"data/meas_2sb_srr_spectrum_lo{lo_frequency/1e9:.0f}ghz_bias{sis_voltage_1*1e3:.2f}mv_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(StateMeasure.data, f, ensure_ascii=False, indent=4)
    logger.info("Data is saved")


def plot_data(p, data):
    items = get_plot_items(p)
    plot_num = max([get_plot_number(name) for name in items.keys()], default=0)
    if data["new_plot"]:
        plot_num += 1
    logger.info(f"Plot Data: {data}")
    graph_id = f"№ {plot_num}; {data['legend_postfix']}"
    p.show()
    if items.get(graph_id):
        item = items.get(graph_id)
        x_data = list(item.xData)
        x_data.extend(data["x"])
        y_data = list(item.yData)
        y_data.extend(data["y"])
        items.get(graph_id).setData(x_data, y_data)
        return

    pen = pg.mkPen(color=colors[plot_num - 1 % len(colors)], width=2)
    p.plot(
        data["x"],
        data["y"],
        name=f"{graph_id}",
        pen=pen,
        symbolSize=6,
        symbolBrush=pen.color(),
    )


def closeEvent(event):
    StateMeasure.thread_running = False
    save_data()
    event.accept()


def main():
    app = pg.mkQApp("2SB SRR Measure")
    win = pg.GraphicsLayoutWidget(show=True, title="Basic plotting examples")
    win.resize(1000, 600)
    win.setWindowTitle(f"2SB SRR Measure {lo_frequency/1e9:.0f} GHz")
    pg.setConfigOptions(antialias=True)
    win.setBackground("w")
    styles = {"color": "#413C58", "font-size": "15px"}

    p1 = win.addPlot()
    p1.setTitle(f"SRR measure {lo_frequency/1e9:.0f} GHz", color="#413C58", size="10pt")
    p1.setLabel("bottom", "IF, GHz", **styles)
    p1.setLabel("left", "Power, dBm", **styles)
    p1.addLegend()
    p1.showGrid(x=True, y=True)

    p2 = win.addPlot()
    p2.setTitle(
        f"Y-factor measure {lo_frequency/1e9:.0f} GHz", color="#413C58", size="10pt"
    )
    p2.setLabel("bottom", "IF, GHz", **styles)
    p2.setLabel("left", "Power, dBm", **styles)
    p2.addLegend()
    p2.showGrid(x=True, y=True)

    thread = MeasThread()
    thread.plot_signal.connect(lambda data: plot_data(p1, data))
    thread.plot2_signal.connect(lambda data: plot_data(p2, data))
    thread.data_signal.connect(collect_data)
    thread.finished.connect(save_data)
    thread.start()
    StateMeasure.thread_running = True

    setattr(win, "closeEvent", closeEvent)
    sys.exit(pg.exec())


if __name__ == "__main__":
    # Parameters
    ###
    measure_y_factor = True
    lo_frequency = 223e9
    inter_frequencies = np.arange(4e9, 12e9, 20e6)
    one_range_len = 20
    inter_frequencies_reshaped = inter_frequencies.reshape(
        len(inter_frequencies) // one_range_len, one_range_len
    )

    sis_voltage_1 = 2.4e-3
    sis_voltage_2 = 2.4e-3

    if_channels = {
        "upper": False,
        "lower": True,
    }

    side_bands = ["upper", "lower"]

    ###

    try:
        main()
    except KeyboardInterrupt:
        save_data()
