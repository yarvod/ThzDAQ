from typing import Dict, List

import numpy as np
import pyqtgraph as pg
from PySide6 import QtGui
from PySide6.QtWidgets import QWidget, QVBoxLayout

from interface.windows.graphWindow import GraphWindow


class SrrIFGraphWindow(GraphWindow):
    window_title = "SRR-IF Graphs"
    graph_title = "Sideband ratio (IF)"
    x_label = "IF, GHz"
    y_label = "P wanted - P image, dB"


class TwoSbCurrentFrequencyGraphWindow(GraphWindow):
    window_title = "2SB I-F Graphs"
    graph_title = "SIS current (Frequency)"
    x_label = "Frequency, GHz"
    y_label = "Current, μA"


class TwoSbMapsGraphWindow(QWidget):
    window_title = "2SB Tn/SRR maps"
    maps = (
        ("tn_upper", "Tn Upper, K", "turbo"),
        ("tn_lower", "Tn Lower, K", "turbo"),
        ("srr_upper", "SRR Upper, dB", "plasma"),
        ("srr_lower", "SRR Lower, dB", "plasma"),
    )

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.png"))
        self.setWindowTitle(self.window_title)
        layout = QVBoxLayout(self)
        self.graphWidget = pg.GraphicsLayoutWidget()
        self.graphWidget.setBackground("w")
        layout.addWidget(self.graphWidget)

        self.images: Dict[str, pg.ImageItem] = {}
        for index, (key, title, colormap) in enumerate(self.maps):
            if index == 2:
                self.graphWidget.nextRow()
            plot = self.graphWidget.addPlot(title=title)
            plot.setLabel("bottom", "SIS 1 voltage, mV")
            plot.setLabel("left", "SIS 2 voltage, mV")
            image = pg.ImageItem()
            plot.addItem(image)
            histogram = pg.HistogramLUTItem()
            histogram.gradient.loadPreset(colormap)
            histogram.setImageItem(image)
            self.graphWidget.addItem(histogram)
            self.images[key] = image

    @staticmethod
    def _step(values: List[float]) -> float:
        return float(values[1] - values[0]) if len(values) > 1 else 1.0

    def update_maps(self, data: Dict):
        """data: voltage_1, voltage_2 (mV) and [v1][v2] matrices with None for gaps"""
        voltage_1 = data["voltage_1"]
        voltage_2 = data["voltage_2"]
        step_1 = self._step(voltage_1)
        step_2 = self._step(voltage_2)
        transform = QtGui.QTransform()
        transform.translate(voltage_1[0] - step_1 / 2, voltage_2[0] - step_2 / 2)
        transform.scale(step_1, step_2)

        for key, image in self.images.items():
            values = np.array(data[key], dtype=float)
            finite = values[np.isfinite(values)]
            if not finite.size:
                continue
            levels = (finite.min(), finite.max())
            if levels[0] == levels[1]:
                levels = (levels[0] - 0.5, levels[1] + 0.5)
            image.setImage(values, levels=levels, autoLevels=False)
            image.setTransform(transform)
