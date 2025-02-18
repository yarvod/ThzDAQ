import logging

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
)

from interface.components.grid.GridBiasCurrentAngleScan import GridBiasCurrentScan
from interface.components.grid.GridManagingGroup import GridManagingGroup

logger = logging.getLogger(__name__)


class GridTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(GridManagingGroup(self))
        self._layout.addSpacing(10)
        self._layout.addWidget(GridBiasCurrentScan(self))
        self._layout.addStretch()

        self.setLayout(self._layout)
