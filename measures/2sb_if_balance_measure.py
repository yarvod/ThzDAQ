# Measuring 2SB IF balance

import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg

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
    data_signal = pg.QtCore.Signal(dict)

    def run(self):
        nrx = NRXPowerMeter(host="169.254.2.20", delay=0)
        yig = NiYIGManager(host="169.254.0.86")
        rs_power = PowerSupplyHMP2030(host="169.254.0.30", port=5025)
        # sis1 = SisBlock(
        #     host="169.254.190.83",
        #     port=9876,
        #     bias_dev="DEV4",
        #     ctrl_dev="DEV3",
        #     offset_voltage=0.04e-3,
        #     offset_current=0,
        # )
        #
        # sis2 = SisBlock(
        #     host="169.254.190.83",
        #     port=9876,
        #     bias_dev="DEV2",
        #     ctrl_dev="DEV1",
        #     offset_voltage=-0.187e-3,
        #     offset_current=-1.3e-6,
        # )

        sis1 = SisBlock(
            host="169.254.71.6",
            port=9876,
            bias_dev="DEV4",
            ctrl_dev="DEV3",
            offset_voltage=0.040e-3,
            offset_current=0,
        )

        sis2 = SisBlock(
            host="169.254.71.6",
            port=9876,
            bias_dev="DEV2",
            ctrl_dev="DEV1",
            offset_voltage=0.205e-3,
            offset_current=0.3e-6,
        )

        data = {"if": inter_frequencies.tolist(), "data": []}
        _data = {}

        try:
            rs_power.set_output_state(2, True)  # Turn On YIG
            send_to_telegram("Measuring 2SB IF balance started")
            logger.info("Measuring 2SB IF balance started")
            for bs1, bs2 in zip(voltages_1, voltages_2):
                logger.info(
                    f"SIS1 voltage {bs1*1e3:.2f}mV; SIS2 voltage {bs2*1e3:.2f}mV;"
                )
                send_to_telegram(
                    f"SIS1 voltage {bs1*1e3:.2f}mV; SIS2 voltage {bs2*1e3:.2f}mV;"
                )
                sis1.set_bias_voltage_iterative(bs1)
                sis2.set_bias_voltage_iterative(bs2)
                _data = {
                    "sis1_voltage": bs1,
                    "sis1_current": sis1.get_bias_current(),
                    "sis2_voltage": bs2,
                    "sis2_current": sis2.get_bias_current(),
                    "power_ch1": [],
                    "power_ch2": [],
                }
                for channel in ["ch1", "ch2"]:
                    rs_power.set_output_state(1, channel == "ch2")
                    logger.info(f"Start measure channel {channel}")
                    send_to_telegram(f"Start measure channel {channel}")
                    time.sleep(1)
                    for freg_ind, freq in enumerate(inter_frequencies):
                        yig.set_frequency(freq)
                        power = nrx.get_power()
                        _data[f"power_{channel}"].append(power)
                        self.plot_signal.emit(
                            {
                                "new_plot": freg_ind == 0,
                                "legend_postfix": f"{channel} {bs1*1e3:.2f}mV {bs2*1e3:.2f}mV",
                                "x": [freq / 1e9],
                                "y": [power],
                            }
                        )

                data["data"].append(_data)
                self.data_signal.emit(data)

        except (Exception, KeyboardInterrupt) as e:
            data["data"].append(_data)
            logger.error(f"Exception: {e}")
            send_to_telegram(f"Exception: {e}")
            self.data_signal.emit(data)

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
        f"data/meas_2sb_if_balance_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
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
    app = pg.mkQApp("2SB IF Balance Measure")
    win = pg.GraphicsLayoutWidget(show=True, title="Basic plotting examples")
    win.resize(1000, 600)
    win.setWindowTitle("2SB IF Balance Measure")
    pg.setConfigOptions(antialias=True)
    win.setBackground("w")
    styles = {"color": "#413C58", "font-size": "15px"}

    p1 = win.addPlot()
    p1.setTitle("IF Balance Measure", color="#413C58", size="10pt")
    p1.setLabel("bottom", "IF, GHz", **styles)
    p1.setLabel("left", "Power, dBm", **styles)
    p1.addLegend()
    p1.showGrid(x=True, y=True)

    thread = MeasThread()
    thread.plot_signal.connect(lambda data: plot_data(p1, data))
    thread.data_signal.connect(collect_data)
    thread.finished.connect(save_data)
    thread.start()
    StateMeasure.thread_running = True

    setattr(win, "closeEvent", closeEvent)
    sys.exit(app.exec())


if __name__ == "__main__":
    # Parameters
    ###

    inter_frequencies = np.arange(4e9, 12e9, 40e6)

    sis_voltage_1 = 5e-3
    sis_voltage_2 = 8e-3

    voltages_1 = [sis_voltage_1, sis_voltage_1, sis_voltage_2, sis_voltage_2]
    voltages_2 = [sis_voltage_1, sis_voltage_2, sis_voltage_1, sis_voltage_2]

    try:
        main()
    except KeyboardInterrupt:
        save_data()
