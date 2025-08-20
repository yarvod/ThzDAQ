import logging

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
)

from interface.components.grid.GridBiasCurrentAngleScan import GridBiasCurrentScan
from interface.components.grid.GridManagingGroup import GridManagingGroup

logger = logging.getLogger(__name__)


class GridTabWidget(QWidget):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(GridManagingGroup(self, cid))
        self._layout.addSpacing(10)
        self._layout.addWidget(GridBiasCurrentScan(self, cid))
        self._layout.addStretch()

        self.setLayout(self._layout)
