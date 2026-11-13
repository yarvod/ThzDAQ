"""Measure SIS current and pump power versus generator amplitude."""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg

from api import PrologixUsb
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
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


class MeasThread(Thread):
    data_signal = pg.QtCore.Signal(dict)

    def __init__(self, amps, parent=None):
        super().__init__(parent)
        self.amps = np.asarray(amps, dtype=float).copy()
        self.data = {
            "currents": [],
            "powers": [],
            "amp": [],
            "current": [],
            "power": [],
            "units": {"amp": "dBm", "current": "A", "power": "dBm"},
        }
        self.status = "Ready"

    def run(self):
        sis = None
        try:
            self.status = "Measuring"
            nrx = NRXPowerMeter(delay=0)
            nrx.set_power_units("DBM")
            sg = PrologixUsb(port="COM6")
            sis = SisBlock(host="169.254.71.6", port=9876, offset_voltage=0)
            sis.connect()
            send_to_telegram("SIS current and pump power measurement started")
            for step_amp, amp in enumerate(self.amps, 1):
                if self.isInterruptionRequested():
                    break
                logger.info(
                    "[%d/%d] Set amplitude %.4f dBm", step_amp, len(self.amps), amp
                )
                sg.write(f"POW {float(amp)}dBm", 18)
                time.sleep(0.1)
                curs = []
                pows = []
                for i in range(10):
                    time.sleep(0.01)
                    curs.append(sis.get_bias_current())
                    pows.append(nrx.get_power())
                current = np.mean(curs)
                power = np.mean(pows)
                if current is None or power is None:
                    raise ValueError("Failed to read SIS current or power meter power")
                if not np.isfinite(current) or not np.isfinite(power):
                    raise ValueError("Non-finite SIS current or power meter power")
                self.data["amp"].append(float(amp))
                self.data["current"].append(float(current))
                self.data["power"].append(float(power))
                self.data["currents"].append(curs)
                self.data["powers"].append(pows)

                self.data_signal.emit(
                    {key: self.data[key].copy() for key in ("amp", "current", "power")}
                )
                logger.info("I=%.2f uA; power=%.4f dBm", current * 1e6, power)
            self.status = "Stopped" if self.isInterruptionRequested() else "Finished"
            send_to_telegram(f"SIS current and pump power measurement: {self.status}")
        except (Exception, KeyboardInterrupt) as error:
            self.status = f"Failed: {error}"
            logger.exception("Measurement failed")
            send_to_telegram(self.status)
        finally:
            if sis is not None:
                try:
                    sis.disconnect()
                except Exception:
                    logger.exception("Failed to disconnect SIS block")


def save_data(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=4, allow_nan=False)
    logger.info("Data saved to %s", path.resolve())


class MeasureWindow(pg.GraphicsLayoutWidget):
    def __init__(self, amps):
        super().__init__(title="SIS Current and Pump Power")
        self.resize(1000, 700)
        self.setBackground("w")
        self.data_is_saved = False
        self.close_requested = False
        self.output_path = Path("data") / (
            f"meas_pump_lo_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        )
        styles = {"color": "#413C58", "font-size": "15px"}
        current_plot = self.addPlot(row=0, col=0)
        power_plot = self.addPlot(row=1, col=0)
        for plot, title, label in (
            (current_plot, "SIS current", "SIS current, uA"),
            (power_plot, "Pump power", "Power, dBm"),
        ):
            plot.setTitle(title, color="#413C58", size="10pt")
            plot.setLabel("bottom", "Generator amplitude, dBm", **styles)
            plot.setLabel("left", label, **styles)
            plot.showGrid(x=True, y=True)
        power_plot.setXLink(current_plot)
        self.current_curve = current_plot.plot(pen=pg.mkPen("#1f77b4", width=2))
        self.power_curve = power_plot.plot(pen=pg.mkPen("#ff7f0e", width=2))
        self.thread = MeasThread(amps, parent=self)
        self.thread.data_signal.connect(self.plot_data)
        self.thread.finished.connect(self.measurement_finished)

    @pg.QtCore.Slot(dict)
    def plot_data(self, data):
        self.current_curve.setData(data["amp"], np.asarray(data["current"]) * 1e6)
        self.power_curve.setData(data["amp"], data["power"])

    def save_data(self):
        if not self.data_is_saved:
            try:
                save_data(self.thread.data, self.output_path)
            except Exception:
                logger.exception("Failed to save measurement data")
                self.setWindowTitle("Save failed - see log; close window to retry")
                return False
            self.data_is_saved = True
        return True

    @pg.QtCore.Slot()
    def measurement_finished(self):
        self.plot_data(self.thread.data)
        self.setWindowTitle(f"SIS Current and Pump Power - {self.thread.status}")
        if self.save_data() and self.close_requested:
            self.close()

    def closeEvent(self, event):
        if self.thread.isRunning():
            self.close_requested = True
            self.thread.requestInterruption()
            self.setWindowTitle("Stopping measurement and saving data...")
            event.ignore()
        elif self.save_data():
            event.accept()
        else:
            event.ignore()


def main():
    app = pg.mkQApp("SIS Current and Pump Power")
    pg.setConfigOptions(antialias=True)
    win = MeasureWindow(np.arange(-10, 4, 0.1))
    win.show()
    win.thread.start()
    try:
        return app.exec()
    finally:
        win.thread.requestInterruption()
        win.thread.wait()
        win.save_data()


if __name__ == "__main__":
    sys.exit(main())
