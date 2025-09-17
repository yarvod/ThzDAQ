# Measuring 2SB SSR and Tn optimization v.s bias
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from alvar import db_to_absolute
from pyqtgraph import ImageItem, HistogramLUTItem, TextItem
from pyqtgraph.Qt import QtGui

from api.Agilent.signal_generator import SignalGenerator
from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.RohdeSchwarz.power_supply import PowerSupplyHMP2030
from api.Scontel.sis_block import SisBlock
from threads import Thread
from utils.functions import (
    send_to_telegram,
    calc_m_dsb,
    calc_r1,
    calc_r2,
    get_if_tn,
    to_db_10,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

logger.setLevel(logging.INFO)


class StateMeasure:
    thread_running = False
    data = {}
    data_is_saved = False


class MeasThread(Thread):
    data_signal = pg.QtCore.Signal(dict)

    def run(self):
        nrx = NRXPowerMeter(host="169.254.2.20", delay=0)
        lo = SignalGenerator(host="169.254.156.103", gpib=19)
        test_tone = SignalGenerator(host="169.254.156.103", gpib=18)
        yig = NiYIGManager(host="169.254.0.86")
        rs_power = PowerSupplyHMP2030(host="169.254.0.30", port=5025, adapter="SOCKET")
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

        data = {
            "if": inter_frequency,
            "lo": lo_frequency,
            "voltage_1": voltage_range_1.tolist(),
            "voltage_2": voltage_range_2.tolist(),
            "srr_optimization": {
                "upper": {
                    "power_upper": [],
                    "power_lower": [],
                },
                "lower": {
                    "power_upper": [],
                    "power_lower": [],
                },
                "srr_upper": np.ones(
                    (len(voltage_range_1), len(voltage_range_2))
                ).tolist(),
                "srr_lower": np.ones(
                    (len(voltage_range_1), len(voltage_range_2))
                ).tolist(),
            },
            "tn_optimization": {
                "power_upper_hot": [],
                "power_lower_hot": [],
                "power_upper_cold": [],
                "power_lower_cold": [],
                "tn_upper": (
                    np.ones((len(voltage_range_1), len(voltage_range_2))) * 40
                ).tolist(),
                "tn_lower": (
                    np.ones((len(voltage_range_1), len(voltage_range_2))) * 40
                ).tolist(),
            },
        }

        try:
            send_to_telegram("Measuring 2SB SSR started")
            logger.info("Measuring 2SB SSR started")

            test_tone.set_rf_output_state(True)
            lo.set_rf_output_state(True)
            lo.set_frequency(lo_frequency / 18)

            rs_power.set_output_state(2, True)  # turn on YIG

            yig.set_frequency(inter_frequency - 1e6)

            chopper_manager.chopper.align_to_hot()

            for step_v1, voltage_1 in enumerate(voltage_range_1):
                sis1.set_bias_voltage_iterative(voltage_1)
                for step_v2, voltage_2 in enumerate(voltage_range_2):
                    # sis1.set_bias_voltage_iterative(voltage_1)
                    sis2.set_bias_voltage_iterative(voltage_2)

                    logger.info(
                        f"Set bias_1={voltage_1*1e3:.2f}mV; bias_2={voltage_2*1e3:.2f}mV"
                    )
                    test_tone.set_rf_output_state(True)
                    time.sleep(0.5)
                    for sideband_rf in side_bands:
                        tt_freq = (
                            lo_frequency + inter_frequency
                            if sideband_rf == "upper"
                            else lo_frequency - inter_frequency
                        )
                        test_tone.set_frequency(tt_freq)
                        time.sleep(0.5)
                        for sideband in if_channels.keys():
                            rs_power.set_output_state(1, if_channels[sideband])
                            time.sleep(1)
                            nrx.get_power()
                            nrx.get_power()
                            power = nrx.get_power()
                            data["srr_optimization"][sideband_rf][
                                f"power_{sideband}"
                            ].append(power)

                    test_tone.set_rf_output_state(False)
                    for sideband in if_channels.keys():
                        chopper_manager.chopper.align_to_cold()
                        time.sleep(0.5)
                        power = nrx.get_power()
                        data["tn_optimization"][f"power_{sideband}_cold"].append(power)

                        chopper_manager.chopper.align_to_hot()
                        time.sleep(0.5)
                        power = nrx.get_power()
                        data["tn_optimization"][f"power_{sideband}_hot"].append(power)

                    tn_upper = get_if_tn(
                        hot_power=data["tn_optimization"]["power_upper_hot"][-1],
                        cold_power=data["tn_optimization"]["power_upper_cold"][-1],
                    )
                    data["tn_optimization"]["tn_upper"][step_v1][step_v2] = tn_upper
                    tn_lower = get_if_tn(
                        hot_power=data["tn_optimization"]["power_lower_hot"][-1],
                        cold_power=data["tn_optimization"]["power_lower_cold"][-1],
                    )
                    data["tn_optimization"]["tn_lower"][step_v1][step_v2] = tn_lower

                    srr_upper, srr_lower = calc_srr(data)
                    srr_upper = to_db_10(srr_upper)
                    srr_lower = to_db_10(srr_lower)
                    data["srr_optimization"]["srr_upper"][step_v1][step_v2] = srr_upper
                    data["srr_optimization"]["srr_lower"][step_v1][step_v2] = srr_lower

                    logger.info(
                        f"Tn_u={tn_upper:.2f}K Tn_l={tn_lower:.2f}K SRR_u={srr_upper:.2f}dB SRR_L={srr_lower:.2f}dB"
                    )
                    self.data_signal.emit(data)

            self.finished.emit()
        except (Exception, KeyboardInterrupt) as e:
            StateMeasure.thread_running = False
            self.data_signal.emit(data)
            logger.error(f"Exception: {e}")
            send_to_telegram(f"Exception: {e}")
            self.finished.emit()

        send_to_telegram(f"Measurement successfully finished!")
        self.finished.emit()


def calc_srr(data):
    m_dsb = calc_m_dsb(
        db_to_absolute(data["tn_optimization"]["power_upper_hot"]),
        db_to_absolute(data["tn_optimization"]["power_upper_cold"]),
        db_to_absolute(data["tn_optimization"]["power_lower_hot"]),
        db_to_absolute(data["tn_optimization"]["power_lower_cold"]),
    )
    mu = db_to_absolute(
        data["srr_optimization"]["upper"]["power_upper"]
    ) / db_to_absolute(data["srr_optimization"]["upper"]["power_lower"])
    ml = db_to_absolute(
        data["srr_optimization"]["lower"]["power_lower"]
    ) / db_to_absolute(data["srr_optimization"]["lower"]["power_upper"])
    r1 = calc_r1(mu, ml, m_dsb)
    r2 = calc_r2(mu, ml, m_dsb)
    return r1[-1], r2[-1]


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
        f"data/meas_2sb_srr_tn_optimization_lo{lo_frequency/1e9:.2f}ghz_if{inter_frequency/1e9:.2f}ghz_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(StateMeasure.data, f, ensure_ascii=False, indent=4)
    logger.info("Data is saved")


def closeEvent(event):
    StateMeasure.thread_running = False
    save_data()
    event.accept()


def update_plot(text_items: list[TextItem], plot_items: list[ImageItem], data):
    # for item in text_items:
    #     item.getViewBox().removeItem(item)
    # text_items = []

    tn_upper_data = np.array(data["tn_optimization"]["tn_upper"])
    tn_lower_data = np.array(data["tn_optimization"]["tn_lower"])
    srr_upper_data = np.array(data["srr_optimization"]["srr_upper"])
    srr_lower_data = np.array(data["srr_optimization"]["srr_lower"])

    plot_items[0].setImage(tn_upper_data, autoLevels=True, autoRange=True)
    plot_items[1].setImage(tn_lower_data, autoLevels=True, autoRange=True)
    plot_items[2].setImage(srr_upper_data, autoLevels=True, autoRange=True)
    plot_items[3].setImage(srr_lower_data, autoLevels=True, autoRange=True)

    # for i, plot_item in enumerate(plot_items):
    #     data = [tn_upper_data, tn_lower_data, srr_upper_data, srr_lower_data][i]
    #     for x in range(data.shape[0]):
    #         for y in range(data.shape[1]):
    #             text_item = TextItem(text=f"{data[x, y]:.1f}", color=(240, 40, 0), anchor=(0.5, 0.5))
    #             text_item.setPos(x, y)
    #             plot_item.getViewBox().addItem(text_item)
    #             text_items.append(text_item)


def main():
    app = pg.mkQApp("2SB SRR and Tn optimization")
    win = pg.GraphicsLayoutWidget()
    win.resize(800, 800)
    win.setWindowTitle(
        f"2SB SRR and Tn optimization LO {lo_frequency/1e9:.2f}GHz IF {inter_frequency/1e9:.2f}GHz"
    )
    win.show()

    plot_items_names = [
        "Tn Upper",
        "Tn Lower",
        "SRR Upper",
        "SRR Lower",
    ]
    plot_items = []
    text_items = []

    for i, name in enumerate(plot_items_names):
        if i == 1:
            win.nextColumn()
        if i == 2:
            win.nextRow()
        if i == 3:
            win.nextColumn()
        plot_item = win.addPlot(title=name)
        img_item = ImageItem()
        plot_item.addItem(img_item)
        plot_items.append(img_item)

        plot_item.setLabel("bottom", "Voltage 1", units="V")
        plot_item.setLabel("left", "Voltage 2", units="V")

        tr = QtGui.QTransform()
        tr.translate(
            voltage_range_2[0] - voltage_step_2 / 2,
            voltage_range_1[0] - voltage_step_1 / 2,
        )
        tr.scale(voltage_step_2, voltage_step_1)

        img_item.setTransform(tr)

        hist_item = HistogramLUTItem()

        if "Tn" in name:
            hist_item.gradient.loadPreset("turbo")
        elif "SRR" in name:
            hist_item.gradient.loadPreset("plasma")

        hist_item.setImageItem(img_item)
        win.addItem(hist_item)

    update_plot(
        text_items,
        plot_items,
        data={
            "voltage_1": voltage_range_1,
            "voltage_2": voltage_range_2,
            "srr_optimization": {
                "srr_upper": np.random.randint(
                    1, 5, (len(voltage_range_1), len(voltage_range_2))
                ),
                "srr_lower": np.random.randint(
                    1, 5, (len(voltage_range_1), len(voltage_range_2))
                ),
            },
            "tn_optimization": {
                "tn_upper": np.random.randint(
                    1, 5, (len(voltage_range_1), len(voltage_range_2))
                ),
                "tn_lower": np.random.randint(
                    1, 5, (len(voltage_range_1), len(voltage_range_2))
                ),
            },
        },
    )

    thread = MeasThread()
    thread.data_signal.connect(collect_data)
    thread.data_signal.connect(lambda x: update_plot(text_items, plot_items, x))
    thread.finished.connect(save_data)
    thread.start()
    StateMeasure.thread_running = True

    setattr(win, "closeEvent", closeEvent)
    sys.exit(app.exec())


if __name__ == "__main__":
    # Parameters
    ###

    parser = argparse.ArgumentParser(description="Process some frequencies.")
    parser.add_argument(
        "--lo_frequency",
        type=float,
        default=223e9,
        help="Local oscillator frequency in Hz",
    )

    args = parser.parse_args()

    # lo_frequency = args.lo_frequency
    lo_frequency = 223e9
    inter_frequency = 5e9

    voltage_step_1 = 0.1e-3
    voltage_step_2 = 0.1e-3
    voltage_range_1 = np.arange(2.1e-3, 2.7e-3, voltage_step_1)
    voltage_range_2 = np.arange(2.1e-3, 2.7e-3, voltage_step_2)

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
