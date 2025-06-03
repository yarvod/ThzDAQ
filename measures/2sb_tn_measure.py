# Measuring 2SB Tn

import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg

from api.Agilent.signal_generator import SignalGenerator
from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.RohdeSchwarz.power_supply import PowerSupplyHMP2030
from api.Scontel.sis_block import SisBlock
from threads import Thread
from utils.functions import send_to_telegram, to_w, get_tn

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
    plot_power_signal = pg.QtCore.Signal(dict)
    plot_tn_signal = pg.QtCore.Signal(dict)
    data_signal = pg.QtCore.Signal(dict)

    def run(self):
        nrx = NRXPowerMeter(host="169.254.2.20", delay=0)
        lo = SignalGenerator(host="169.254.156.103", gpib=19)
        yig = NiYIGManager(host="169.254.0.86")
        rs_power = PowerSupplyHMP2030(host="169.254.0.30", port=5025)
        sis2 = SisBlock(
            host="169.254.190.83",
            port=9876,
            bias_dev="DEV2",
            ctrl_dev="DEV3",
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

        data = {
            "p_upper_hot": [],
            "p_upper_cold": [],
            "p_lower_hot": [],
            "p_lower_cold": [],
            "y_factor_upper": [],
            "y_factor_lower": [],
            "tn_upper": [],
            "tn_lower": [],
        }

        try:
            send_to_telegram("Measuring 2SB Tn started")
            logger.info("Measuring 2SB Tn started")

            lo.set_rf_output_state(True)
            lo.set_frequency(lo_frequency / 18)

            chopper_manager.chopper.align_to_cold()
            rs_power.set_output_state(2, True)  # turn on YIG

            logger.info("Start measuring Y-factor")

            for side_band in side_bands:
                rs_power.set_output_state(1, if_channels[side_band])
                for chopper_state in ["cold", "hot"]:
                    logger.info(f"Channel {side_band} Load {chopper_state}")
                    rotate = getattr(
                        chopper_manager.chopper, f"align_to_{chopper_state}"
                    )
                    rotate()
                    sis2.set_bias_voltage(sis_voltage_2)
                    sis1.set_bias_voltage_iterative(sis_voltage_1)
                    for fi, freq in enumerate(inter_frequencies):
                        yig.set_frequency(freq)
                        time.sleep(0.01)
                        power = nrx.get_power()
                        data[f"p_{side_band}_{chopper_state}"].append(power)
                        self.data_signal.emit(data)
                        self.plot_power_signal.emit(
                            {
                                "new_plot": fi == 0,
                                "legend_postfix": f"{side_band} {chopper_state}",
                                "x": [freq / 1e9],
                                "y": [power],
                            }
                        )

                y_factor = np.array(data[f"p_{side_band}_hot"]) - np.array(
                    data[f"p_{side_band}_cold"]
                )
                data[f"y_factor_{side_band}"] = y_factor.tolist()
                self.data_signal.emit(data)

                self.plot_power_signal.emit(
                    {
                        "new_plot": True,
                        "legend_postfix": f"{side_band} Y-factor",
                        "x": inter_frequencies / 1e9,
                        "y": y_factor,
                    }
                )

                tn = get_tn(
                    to_w(data[f"p_{side_band}_hot"]) / to_w(data[f"p_{side_band}_cold"])
                )
                data[f"tn_{side_band}"] = tn.tolist()
                self.data_signal.emit(data)

                self.plot_tn_signal.emit(
                    {
                        "new_plot": True,
                        "legend_postfix": f"{side_band} T_n",
                        "x": inter_frequencies / 1e9,
                        "y": tn,
                    }
                )

            chopper_manager.chopper.align_to_cold()

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
        f"data/meas_2sb_tn_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
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
    app = pg.mkQApp("2SB Tn Measure")
    win = pg.GraphicsLayoutWidget(show=True, title="2SB Tn Measure")
    win.resize(1000, 600)
    win.setWindowTitle("2SB Tn Measure")
    pg.setConfigOptions(antialias=True)
    win.setBackground("w")
    styles = {"color": "#413C58", "font-size": "15px"}

    p1 = win.addPlot()
    p1.setTitle("Power measure", color="#413C58", size="10pt")
    p1.setLabel("bottom", "IF, GHz", **styles)
    p1.setLabel("left", "Power, dBm", **styles)
    p1.addLegend()
    p1.showGrid(x=True, y=True)

    p2 = win.addPlot()
    p2.setTitle("Tn measure", color="#413C58", size="10pt")
    p2.setLabel("bottom", "IF, GHz", **styles)
    p2.setLabel("left", "Tn, K", **styles)
    p2.addLegend()
    p2.showGrid(x=True, y=True)

    thread = MeasThread()
    thread.plot_power_signal.connect(lambda data: plot_data(p1, data))
    thread.plot_tn_signal.connect(lambda data: plot_data(p2, data))
    thread.data_signal.connect(collect_data)
    thread.finished.connect(save_data)
    thread.start()
    StateMeasure.thread_running = True

    setattr(win, "closeEvent", closeEvent)
    sys.exit(pg.exec())


if __name__ == "__main__":
    # Parameters
    ###
    lo_frequency = 263e9
    inter_frequencies = np.arange(4e9, 12e9, 40e6)

    sis_voltage_1 = 2.5e-3
    sis_voltage_2 = 2.5e-3

    if_channels = {
        "upper": True,
        "lower": False,
    }

    side_bands = ["upper", "lower"]

    ###

    try:
        main()
    except KeyboardInterrupt:
        save_data()
