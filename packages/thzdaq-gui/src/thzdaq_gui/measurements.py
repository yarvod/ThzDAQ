"""Measurements of this session (and files opened) as a table model for the Data dock."""

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from thzdaq_core.data.measurement import (
    CANCELLED,
    COMPLETED,
    FAILED,
    INTERRUPTED,
    RUNNING,
    Measurement,
)
from thzdaq_core.data.store import MeasurementStore, read_json

from thzdaq_gui import theme

COLUMNS = ("Id", "Measurement", "Comment", "Started", "Finished", "Status", "Points")
STATUS_COLORS = {
    RUNNING: theme.ACCENT,
    COMPLETED: "#81c784",
    CANCELLED: theme.MUTED,
    FAILED: "#e57373",
    INTERRUPTED: "#e57373",
}


def short_time(stamp: Optional[str]) -> str:
    return stamp.replace("T", " ")[:19] if stamp else "--"


class MeasurementsModel(QAbstractTableModel):
    """Newest first; comments are editable and saved to the file at once."""

    measurement_added = Signal(object)

    def __init__(self, store: MeasurementStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.items: List[Measurement] = []
        self.counter = 0  # run numbers in curve names: #1, #2, ...

    # Qt model
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.column() == 2:
            flags |= Qt.ItemIsEditable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        column = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            return (
                item.id,
                item.title or item.procedure,
                item.comment,
                short_time(item.started),
                short_time(item.finished),
                item.status,
                item.size,
            )[column]
        if role == Qt.ForegroundRole and column == 5:
            from PySide6.QtGui import QColor

            return QColor(STATUS_COLORS.get(item.status, theme.TEXT))
        if role == Qt.ToolTipRole:
            return item.metadata.get("path") or item.error or None
        return None

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or index.column() != 2:
            return False
        item = self.items[index.row()]
        item.comment = str(value)
        if item.status != RUNNING:
            self.save(item)
        self.dataChanged.emit(index, index)
        return True

    # Items
    def measurement(self, row: int) -> Measurement:
        return self.items[row]

    def add(self, measurement: Measurement) -> None:
        if any(item is measurement for item in self.items):
            return
        self.counter += 1
        measurement.metadata.setdefault("number", self.counter)
        self.beginInsertRows(QModelIndex(), 0, 0)
        self.items.insert(0, measurement)
        self.endInsertRows()
        self.measurement_added.emit(measurement)

    def refresh_item(self, measurement: Measurement) -> None:
        for row, item in enumerate(self.items):
            if item is measurement:
                self.dataChanged.emit(
                    self.index(row, 0), self.index(row, len(COLUMNS) - 1)
                )

    def refresh(self) -> None:
        if self.items:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.items) - 1, len(COLUMNS) - 1)
            )

    def remove(self, row: int) -> None:
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.items[row]
        self.endRemoveRows()

    def open(self, path) -> Measurement:
        path = str(Path(path))
        for item in self.items:
            if item.metadata.get("path") == path:
                return item
        measurement = read_json(path)
        self.add(measurement)
        return measurement

    def save(self, measurement: Measurement, path=None) -> Path:
        return self.store.save(measurement, path or measurement.metadata.get("path"))
