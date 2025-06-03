"""
Измерение Шумовой температуры от ПЧ для разных напряжениях СИС смесителя
"""

import json
import logging
import re
import sys
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg

from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.Scontel.sis_block import SisBlock
from store.state import state
from utils.functions import send_to_telegram, get_if_tn
from utils.logger import configure_logger

# Настройка логгера
configure_logger()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Цвета для графиков
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
        # Инициализация оборудования
        sis = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev="DEV2",
            ctrl_dev="DEV1",
        )
        sis.connect()
        ni_yig = NiYIGManager(host=state.NI_IP)
        nrx = NRXPowerMeter(delay=0, aperture_time=50)

        # Параметры измерений
        voltages_range = np.arange(2.3, 3.2, 0.1) * 1e-3
        freq_range = np.linspace(3, 13, 300) * 1e9

        data = {
            "type": "Tn(IF) for different SIS bias voltages",
            "t_hot": 300,
            "t_cold": 77,
            "frequency": freq_range.tolist(),
            "data": [],
        }

        try:
            chopper_manager.chopper.align_to_cold()
            for voltage_step, voltage in enumerate(voltages_range, 1):
                logger.info(f"Start for voltage = {voltage*1e3:.3f}")
                send_to_telegram(f"Start for voltage = {voltage*1e3:.3f}")

                _data = {
                    "voltage": voltage,
                    "hot_power": [],
                    "cold_power": [],
                    "y_factor": [],
                    "tn": [],
                }

                # Измерение при горячей нагрузке
                logger.info("Hot measure...")
                chopper_manager.chopper.path0()
                time.sleep(2)
                sis.set_bias_voltage(voltage)
                for freq_step, freq in enumerate(freq_range, 1):
                    ni_yig.set_frequency(freq)
                    time.sleep(0.01)
                    power = nrx.get_power()
                    _data["hot_power"].append(power)
                    self.plot_signal.emit(
                        {
                            "new_plot": False,
                            "legend_postfix": f"Hot {voltage*1e3:.3f}mV",
                            "x": [freq / 1e9],
                            "y": [power],
                        }
                    )

                # Измерение при холодной нагрузке
                logger.info("Cold measure...")
                chopper_manager.chopper.path0()
                time.sleep(2)
                sis.set_bias_voltage(voltage)
                for freq_step, freq in enumerate(freq_range, 1):
                    ni_yig.set_frequency(freq)
                    time.sleep(0.01)
                    power = nrx.get_power()
                    _data["cold_power"].append(power)
                    self.plot_signal.emit(
                        {
                            "new_plot": False,
                            "legend_postfix": f"Cold {voltage*1e3:.3f}mV",
                            "x": [freq / 1e9],
                            "y": [power],
                        }
                    )

                _data["y_factor"] = (
                    np.array(_data["hot_power"]) - np.array(_data["cold_power"])
                ).tolist()
                _data["tn"] = get_if_tn(
                    _data["hot_power"],
                    _data["cold_power"],
                    th=data["t_hot"],
                    tc=data["t_cold"],
                ).tolist()
                data["data"].append(_data)
                self.data_signal.emit(data)

        except (Exception, KeyboardInterrupt) as e:
            logger.error(f"Exception: {e}")
            send_to_telegram(f"Exception: {e}")
            sis.set_bias_voltage(0)
            chopper_manager.chopper.align_to_cold()
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
    try:
        with open(
            f"data/meas_tn_if_sis_bias_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(StateMeasure.data, f, ensure_ascii=False, indent=4)
    except (FileNotFoundError, Exception):
        with open(
            f"meas_tn_if_sis_bias_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
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
    app = pg.mkQApp("Tn(IF) Measure")
    win = pg.GraphicsLayoutWidget(show=True, title="Basic plotting examples")
    win.resize(1000, 600)
    win.setWindowTitle("Tn(IF) Measure")
    pg.setConfigOptions(antialias=True)
    win.setBackground("w")
    styles = {"color": "#413C58", "font-size": "15px"}

    p1 = win.addPlot()
    p1.setTitle("Tn(IF) Measure", color="#413C58", size="10pt")
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
    sys.exit(pg.exec())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        save_data()
