"""Measurements of this window as a table model for the Data dock: those it
started or saw running, those the daemon remembers (their files are read
when they are plotted) and files opened. Each knows the workspace it was
made in: Data shows the window's own, and the others on asking, marked with
where they are from.

A comment goes to the daemon (set_comment): it writes the file, or keeps the
comment of a running measurement with its data."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from thzdaq_api.measurement_file import (
    CANCELLED,
    COMPLETED,
    CONFLICTS,
    FAILED,
    INTERRUPTED,
    RUNNING,
    Measurement,
    read_measurement,
    write_measurement,
)
from thzdaq_api.measurements import RunInfo, SetComment

from thzdaq_gui import theme
from thzdaq_gui.models.run import measurement_of

COLUMNS = ("Id", "Measurement", "Comment", "Started", "Finished", "Status", "Points")
STATUS_COLORS = {
    RUNNING: theme.ACCENT,
    COMPLETED: theme.GOOD,
    CANCELLED: theme.MUTED,
    FAILED: theme.BAD,
    INTERRUPTED: theme.BAD,
}


def short_time(stamp: Optional[str]) -> str:
    return stamp.replace("T", " ")[:19] if stamp else "--"


def conflicts_text(conflicts) -> str:
    """For a tooltip: what others did to the devices it swept, accepted."""
    lines = [
        ", ".join(f"{key} {value}" for key, value in entry.items() if key != "at")
        for entry in conflicts
    ]
    return "Conflicts accepted (share):\n" + "\n".join(lines)


@dataclass
class Row:
    measurement: Measurement
    workspace: Optional[str]  # where it was made; None: a file opened here
    run: Optional[RunInfo] = None  # a run the daemon remembers, its file unread


class MeasurementsModel(QAbstractTableModel):
    """Newest first; comments are editable and saved to the file at once."""

    measurement_added = Signal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        # Its lab writes comments, its worker calls it, its workspace is here
        self.session = session
        self.rows: List[Row] = []
        session.workspace.changed.connect(self.refresh)

    @property
    def items(self) -> List[Measurement]:
        return [row.measurement for row in self.rows]

    def measured(self) -> List[Measurement]:
        """Those whose records are here (a remembered run's once plotted)."""
        return [row.measurement for row in self.rows if row.run is None]

    def here(self, row: int) -> bool:
        """Made in the window's workspace, or opened here."""
        workspace = self.rows[row].workspace
        return workspace is None or self.session.workspace.holds(workspace)

    # Qt model
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

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
        row = self.rows[index.row()]
        item = row.measurement
        column = index.column()
        elsewhere = not self.here(index.row())
        if role in (Qt.DisplayRole, Qt.EditRole):
            title = self.title(item)
            return (
                item.id,
                f"{title} · from {Path(row.workspace).name}" if elsewhere else title,
                item.comment,
                short_time(item.started),
                short_time(item.finished),
                item.status,
                row.run.done if row.run is not None else item.size,
            )[column]
        if role == Qt.ToolTipRole and column == 1:
            told = [f"Measured in {row.workspace}"] if elsewhere else []
            if self.title(item) != (item.title or item.procedure):
                told.append(f"Measured as {item.title} ({item.procedure})")
            if told:
                return "\n".join(told)
        conflicts = item.metadata.get(CONFLICTS) or ()
        if role == Qt.ForegroundRole and column == 5:
            from PySide6.QtGui import QColor

            return QColor(STATUS_COLORS.get(item.status, theme.TEXT))
        if role == Qt.DecorationRole and column == 5 and conflicts:
            return theme.icon("alert-outline", theme.ACCENT)
        if role == Qt.ToolTipRole:
            if column == 5 and conflicts:
                return conflicts_text(conflicts)
            return item.metadata.get("path") or item.error or None
        return None

    def title(self, item: Measurement) -> str:
        """The title its procedure has now; the one it was measured with
        when the bench has the procedure no more."""
        about = self.session.procedure(item.procedure)
        return about.title if about is not None else item.title or item.procedure

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or index.column() != 2:
            return False
        item = self.rows[index.row()].measurement
        item.comment = str(value)
        path = item.metadata.get("path")
        if path:
            lab, comment = self.session.lab, SetComment(path=path, comment=item.comment)
            self.session.calls.submit(lambda: lab.call(comment))
        self.dataChanged.emit(index, index)
        return True

    # Items
    def measurement(self, row: int) -> Measurement:
        """With its records: a remembered run's file is read now (it stays
        as the daemon told it when the file is gone)."""
        found = self.rows[row]
        if found.run is not None:
            try:
                found.measurement = read_measurement(found.run.path)
            except (OSError, ValueError):
                return found.measurement
            found.run = None
            self._changed(row)
        return found.measurement

    def add(self, measurement: Measurement, workspace: Optional[str] = None) -> None:
        """A measurement made in workspace (None: a file opened here)."""
        if any(item is measurement for item in self.items):
            return
        self._insert(Row(measurement, workspace))
        self.measurement_added.emit(measurement)

    def remember(self, run: RunInfo) -> None:
        """A run that ended before this window saw it, as the daemon remembers
        it; its file is read when it is plotted."""
        if run.path is None or self._row_of(run.path) is not None:
            return
        self._insert(
            Row(measurement_of(run, self.session.title_of), run.workspace, run)
        )

    def _insert(self, row: Row) -> None:
        self.beginInsertRows(QModelIndex(), 0, 0)
        self.rows.insert(0, row)
        self.endInsertRows()

    def _row_of(self, path: str) -> Optional[int]:
        """The row of the measurement whose file is path; None for none."""
        return next(
            (
                row
                for row, item in enumerate(self.items)
                if item.metadata.get("path") == path
            ),
            None,
        )

    def refresh_item(self, measurement: Measurement) -> None:
        for row, item in enumerate(self.items):
            if item is measurement:
                self._changed(row)

    def _changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def refresh(self) -> None:
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMNS) - 1)
            )

    def remove(self, row: int) -> None:
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.rows[row]
        self.endRemoveRows()

    def open(self, path) -> Measurement:
        path = str(Path(path))
        listed = self._row_of(path)
        if listed is not None:
            return self.measurement(listed)
        measurement = read_measurement(path)
        self.add(measurement)
        return measurement

    def kept(self, row: int) -> Measurement:
        """As its file keeps it: its parameters, its devices with their
        settings, the station, its results, its plots and every record. The
        window's own copy holds only what the run's events told (its records
        and how it ended); one without a file, or whose file is gone, is that
        copy. A running one's file tells what it holds so far and that it is
        not over: its status and comment are those the window follows."""
        item = self.measurement(row)
        path = item.metadata.get("path")
        if not path:
            return item
        try:
            found = read_measurement(path)
        except ValueError:  # gone, or no longer a measurement
            return item
        found.status, found.comment = item.status, item.comment
        return found

    def save_copy(self, row: int, path) -> Path:
        """A copy where a person chose (the daemon keeps the original)."""
        return write_measurement(self.kept(row), path)
