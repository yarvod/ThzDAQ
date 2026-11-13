import json
import logging
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from api import SisBlock
from api.SRS.LockIn_SR830 import LockIn
from settings import PROLOGIX_ETHERNET


logger = logging.getLogger(__name__)
DATA_FIELDS = ("time", "set_voltage", "voltage", "current", "lockin")


def save_data(path, data, metadata):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as stream:
        json.dump(
            {"metadata": metadata, "data": data},
            stream,
            ensure_ascii=False,
            indent=4,
            allow_nan=False,
        )
    temporary_path.replace(path)


class MeasThread(QThread):
    data_signal = Signal(dict)

    def __init__(self, bias_list, point_time, output_path, parent=None):
        super().__init__(parent)
        self.bias_list = [float(voltage) for voltage in bias_list]
        if not self.bias_list or not all(map(math.isfinite, self.bias_list)):
            raise ValueError("Bias sweep must contain finite voltages")
        if not math.isfinite(point_time) or point_time < 0:
            raise ValueError("Point time must be finite and non-negative")
        self.point_time = point_time
        self.output_path = Path(output_path)
        self.stop_event = Event()
        self.error = ""
        self.status = "running"

    def stop(self):
        self.stop_event.set()

    def run(self):
        data = {field: [] for field in DATA_FIELDS}
        metadata = {
            "started_at": datetime.now().astimezone().isoformat(),
            "point_time": self.point_time,
            "bias_list": self.bias_list,
            "units": {
                "time": "s",
                "set_voltage": "V",
                "voltage": "V",
                "current": "A",
                "lockin": "V",
            },
            "lockin_output": "OUTP? 3",
            "status": self.status,
        }
        instruments = []
        try:
            save_data(self.output_path, data, metadata)
            sis = SisBlock(host="169.254.71.6", port=9876, offset_voltage=0)
            instruments.append(sis)
            lockin = LockIn(
                host="169.254.156.103", port=1234, adapter=PROLOGIX_ETHERNET
            )
            instruments.append(lockin)
            started = time.monotonic()
            for bias in self.bias_list:
                if self.stop_event.is_set():
                    break
                sis.set_bias_voltage(bias)
                if self.stop_event.wait(self.point_time):
                    break
                values = {
                    "voltage": sis.get_bias_voltage(),
                    "current": sis.get_bias_current(),
                    "lockin": lockin.get_out3(),
                }
                for field, value in values.items():
                    if value is None or not math.isfinite(value):
                        raise ValueError(f"Invalid {field} reading: {value}")
                point = {
                    "time": time.monotonic() - started,
                    "set_voltage": bias,
                    **values,
                }
                for field in DATA_FIELDS:
                    data[field].append(point[field])
                self.data_signal.emit(point)
                save_data(self.output_path, data, metadata)
            self.status = "stopped" if self.stop_event.is_set() else "completed"
        except Exception as error:
            self.status = "error"
            self.error = str(error)
            logger.exception("Bias measurement failed")
        finally:
            for instrument in reversed(instruments):
                try:
                    instrument.adapter.close()
                except Exception:
                    logger.exception("Unable to close instrument connection")
            metadata.update(
                status=self.status,
                error=self.error,
                finished_at=datetime.now().astimezone().isoformat(),
            )
            try:
                save_data(self.output_path, data, metadata)
            except Exception as error:
                self.status = "error"
                self.error = f"{self.error}\nUnable to save data: {error}".strip()
                logger.exception("Unable to save measurement data")


class MeasurementWindow(QWidget):
    def __init__(self, bias_list, point_time, output_path):
        super().__init__()
        self.setWindowTitle("SIS I-V / Lock-in vs bias")
        self.resize(1000, 800)
        self.data = {field: [] for field in DATA_FIELDS}
        self.close_requested = False
        self.measurement_finished = False

        layout = QVBoxLayout(self)
        self.iv_plot = pg.PlotWidget(title="SIS I-V")
        self.iv_plot.setLabel("left", "SIS current", units="A")
        self.lockin_plot = pg.PlotWidget(title="Lock-in R vs SIS voltage")
        self.lockin_plot.setLabel("left", "Lock-in R", units="V")
        for plot in (self.iv_plot, self.lockin_plot):
            plot.setLabel("bottom", "Measured SIS voltage", units="V")
            plot.showGrid(x=True, y=True, alpha=0.3)
            layout.addWidget(plot)
        self.lockin_plot.setXLink(self.iv_plot)
        self.iv_curve = self.iv_plot.plot(pen=pg.mkPen("c", width=2), symbol="o")
        self.lockin_curve = self.lockin_plot.plot(
            pen=pg.mkPen("y", width=2), symbol="o"
        )
        self.status_label = QLabel("Connecting to instruments...")
        layout.addWidget(self.status_label)
        path_label = QLabel(f"Data: {output_path}")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        self.stop_button = QPushButton("Stop and save")
        layout.addWidget(self.stop_button)

        self.worker = MeasThread(bias_list, point_time, output_path, self)
        self.worker.data_signal.connect(self.update_data)
        self.worker.finished.connect(self.finish_measurement)
        self.stop_button.clicked.connect(self.stop_measurement)
        self.worker.start()

    @Slot(dict)
    def update_data(self, point):
        for field in DATA_FIELDS:
            self.data[field].append(point[field])
        self.iv_curve.setData(self.data["voltage"], self.data["current"])
        self.lockin_curve.setData(self.data["voltage"], self.data["lockin"])
        progress = f"{len(self.data['time'])}/{len(self.worker.bias_list)} points"
        if self.worker.stop_event.is_set():
            self.status_label.setText(f"Stopping... {progress}")
        else:
            self.status_label.setText(
                f"{progress} | U = {point['voltage'] * 1e3:.4f} mV | "
                f"I = {point['current'] * 1e6:.4f} uA | "
                f"R = {point['lockin']:.6g} V"
            )

    @Slot()
    def stop_measurement(self):
        self.worker.stop()
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping after the current instrument operation...")

    @Slot()
    def finish_measurement(self):
        self.worker.wait()
        self.measurement_finished = True
        self.stop_button.setEnabled(False)
        if self.worker.error:
            self.status_label.setText("Measurement failed; see error details.")
            QMessageBox.critical(self, "Measurement error", self.worker.error)
        else:
            self.status_label.setText(
                f"{self.worker.status.capitalize()}: "
                f"{len(self.data['time'])} points saved."
            )
        if self.close_requested:
            self.close()

    def closeEvent(self, event):
        if not self.measurement_finished:
            self.close_requested = True
            self.stop_measurement()
            event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    point_time = 0.4
    bias = np.linspace(0, 4e-3, 161)
    output_path = (
        Path(__file__).resolve().parent
        / "data"
        / f"meas_bias_lockin_{datetime.now():%Y-%m-%d_%H-%M-%S_%f}.json"
    )
    app = QApplication(sys.argv)
    window = MeasurementWindow(bias.tolist(), point_time, output_path)
    window.show()
    sys.exit(app.exec())
