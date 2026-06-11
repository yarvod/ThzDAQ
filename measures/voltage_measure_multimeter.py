import json
import logging
import sys
import time
from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from api.Keithley.multimeter import Multimeter

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

HOST = "169.254.156.103"
GPIB = 26
SAMPLE_INTERVAL_S = 0.0
DEFAULT_DISPLAY_POINTS = 2000


def save_data(data, filename=None):
    if filename is None:
        filename = (
            f"meas_block_voltage_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        )

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

    logger.info("Data is saved to %s", filename)
    return filename


class VoltageMeasureThread(QThread):
    point_ready = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        host=HOST,
        gpib=GPIB,
        sample_interval=SAMPLE_INTERVAL_S,
        parent=None,
    ):
        super().__init__(parent)
        self.host = host
        self.gpib = gpib
        self.sample_interval = float(sample_interval)
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            multimeter = Multimeter(host=self.host, gpib=self.gpib)
            multimeter.set_range("R0")
            start_time = time.monotonic()
            step = 0

            while self._running:
                step += 1

                elapsed = time.monotonic() - start_time

                voltage = multimeter.get_voltage()
                if voltage is None:
                    raise ValueError("Multimeter returned empty voltage response")

                timestamp = datetime.now().strftime("%T.%f")
                point = {
                    "step": step,
                    "voltage": float(voltage),
                    "time": timestamp,
                    "elapsed": elapsed,
                }
                self.point_ready.emit(point)
                print(
                    f"[{step}] "
                    f"time: {timestamp}; elapsed: {elapsed:.3f}s; "
                    f"volt: {float(voltage):.6g}"
                )

                self._sleep_interruptibly()
        except (Exception, KeyboardInterrupt) as err:
            self.error.emit(str(err))

    def _sleep_interruptibly(self):
        if self.sample_interval <= 0:
            return

        deadline = time.monotonic() + self.sample_interval
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.05, deadline - time.monotonic()))


class VoltageMonitorWindow(QWidget):
    def __init__(
        self,
        host=HOST,
        gpib=GPIB,
        sample_interval=SAMPLE_INTERVAL_S,
    ):
        super().__init__()
        self.setWindowTitle("Multimeter Voltage Monitor")
        self.resize(1000, 650)

        self.data = {
            "voltage": [],
            "time": [],
            "elapsed": [],
            "step": [],
        }
        self._save_filename = None
        self._saved_points_count = 0
        self._follow_latest_count = True

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Voltage monitoring is running")

        display_layout = QHBoxLayout()
        latest_count_label = QLabel("Latest count:")
        self.display_points_spin = QSpinBox()
        self.display_points_spin.setRange(1, 1_000_000)
        self.display_points_spin.setValue(DEFAULT_DISPLAY_POINTS)
        self.display_points_spin.setSingleStep(100)
        self.display_points_spin.setToolTip(
            "Only this many latest points are drawn. All measured points are still saved."
        )

        from_label = QLabel("From point:")
        self.display_from_spin = QSpinBox()
        self.display_from_spin.setRange(1, 1_000_000)
        self.display_from_spin.setValue(1)
        self.display_from_spin.setToolTip("First point index to draw, starting from 1.")

        to_label = QLabel("To point:")
        self.display_to_spin = QSpinBox()
        self.display_to_spin.setRange(0, 1_000_000)
        self.display_to_spin.setSpecialValueText("latest")
        self.display_to_spin.setValue(0)
        self.display_to_spin.setToolTip(
            "Last point index to draw. Use 'latest' to follow new points live."
        )

        display_layout.addWidget(latest_count_label)
        display_layout.addWidget(self.display_points_spin)
        display_layout.addWidget(from_label)
        display_layout.addWidget(self.display_from_spin)
        display_layout.addWidget(to_label)
        display_layout.addWidget(self.display_to_spin)
        display_layout.addStretch(1)

        self.voltage_plot = pg.PlotWidget(title="Voltage vs Time")
        self.voltage_plot.setBackground("w")
        self.voltage_plot.showGrid(x=True, y=True, alpha=0.3)
        self.voltage_plot.setLabel("bottom", "Time", units="s")
        self.voltage_plot.setLabel("left", "Voltage", units="V")
        self.voltage_curve = self.voltage_plot.plot(
            pen=pg.mkPen((220, 40, 40), width=2),
            symbol="o",
            symbolSize=5,
            symbolBrush=(220, 40, 40),
        )

        buttons_layout = QHBoxLayout()
        self.stop_button = QPushButton("Stop")
        self.save_button = QPushButton("Save")
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.save_button)
        buttons_layout.addStretch(1)

        layout.addWidget(self.status_label)
        layout.addLayout(display_layout)
        layout.addWidget(self.voltage_plot)
        layout.addLayout(buttons_layout)

        self.thread = VoltageMeasureThread(
            host=host,
            gpib=gpib,
            sample_interval=sample_interval,
            parent=self,
        )
        self.thread.point_ready.connect(self._append_point)
        self.thread.error.connect(self._on_error)
        self.thread.finished.connect(self._on_finished)
        self.stop_button.clicked.connect(self._stop_measure)
        self.save_button.clicked.connect(self._save)
        self.display_points_spin.valueChanged.connect(self._on_latest_count_changed)
        self.display_from_spin.valueChanged.connect(self._on_display_range_changed)
        self.display_to_spin.valueChanged.connect(self._on_display_range_changed)
        self.thread.start()

    def _append_point(self, point):
        self.data["step"].append(int(point["step"]))
        self.data["voltage"].append(float(point["voltage"]))
        self.data["time"].append(point["time"])
        self.data["elapsed"].append(float(point["elapsed"]))

        if self._follow_latest_count:
            self._apply_latest_count_range()

        self._update_plot_data()
        self.status_label.setText(
            f"Samples: {len(self.data['voltage'])} | "
            f"displayed: {self._displayed_points_count()} | "
            f"t={self.data['elapsed'][-1]:.2f}s | "
            f"voltage={self.data['voltage'][-1]:.6g} V"
        )

    def _on_latest_count_changed(self, _value):
        self._follow_latest_count = True
        self._apply_latest_count_range()
        self._update_plot_data()

    def _on_display_range_changed(self, _value):
        self._follow_latest_count = False
        self._update_plot_data()

    def _apply_latest_count_range(self):
        total_points = len(self.data["voltage"])
        if total_points <= 0:
            return

        start_point = max(1, total_points - int(self.display_points_spin.value()) + 1)
        self.display_from_spin.blockSignals(True)
        self.display_to_spin.blockSignals(True)
        self.display_from_spin.setValue(start_point)
        self.display_to_spin.setValue(0)
        self.display_from_spin.blockSignals(False)
        self.display_to_spin.blockSignals(False)

    def _display_range_indices(self):
        total_points = len(self.data["voltage"])
        if total_points == 0:
            return 0, 0

        start_point = int(self.display_from_spin.value())
        end_point = int(self.display_to_spin.value())
        if end_point == 0:
            end_point = total_points

        start_point = max(1, min(start_point, total_points))
        end_point = max(1, min(end_point, total_points))
        if end_point < start_point:
            start_point, end_point = end_point, start_point

        return start_point - 1, end_point

    def _displayed_points_count(self):
        start_idx, end_idx = self._display_range_indices()
        return max(0, end_idx - start_idx)

    def _update_plot_data(self):
        start_idx, end_idx = self._display_range_indices()
        self.voltage_curve.setData(
            self.data["elapsed"][start_idx:end_idx],
            self.data["voltage"][start_idx:end_idx],
        )

    def _on_error(self, message):
        self.status_label.setText(f"Voltage monitoring error: {message}")
        self._save()

    def _on_finished(self):
        self._save()
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"{self.status_label.text()} | stopped")

    def _stop_measure(self):
        self.thread.stop()
        self.stop_button.setEnabled(False)

    def _save(self):
        if not self.data["voltage"]:
            return

        if self._saved_points_count == len(self.data["voltage"]):
            return

        self._save_filename = save_data(self.data, self._save_filename)
        self._saved_points_count = len(self.data["voltage"])
        self.status_label.setText(
            f"{self.status_label.text()} | saved: {self._save_filename}"
        )

    def closeEvent(self, event):
        if self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(3000)

        self._save()
        event.accept()


def main():
    pg.setConfigOptions(antialias=True)
    app = QApplication(sys.argv)
    window = VoltageMonitorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Voltage monitoring interrupted")
