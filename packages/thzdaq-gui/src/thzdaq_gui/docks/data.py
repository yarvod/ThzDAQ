"""Data dock: measurements of the session and opened files, as the old table.

Every measurement is saved to data/<date>/ as it runs; here it can be
commented, plotted again, saved elsewhere as JSON or exported to CSV.
"""

import json
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QPlainTextEdit,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.data.store import dumps, export_csv

from thzdaq_gui import theme


class DetailsDialog(QDialog):
    def __init__(self, measurement, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            f"{measurement.title or measurement.procedure} {measurement.id}"
        )
        self.resize(640, 560)
        data = measurement.to_dict()
        # The data itself is in the tables; show their sizes, not every value
        data["tables"] = {
            name: {
                "title": t.title,
                "rows": len(t),
                "columns": [c.label for c in t.columns],
            }
            for name, t in measurement.tables.items()
        }
        text = QPlainTextEdit(
            json.dumps(json.loads(dumps(data)), indent=2, ensure_ascii=False)
        )
        text.setReadOnly(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        layout.addWidget(buttons)


class DataWidget(QWidget):
    plot_requested = Signal(object)  # Measurement

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.model = session.measurements
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        for icon_name, tip, slot in (
            ("folder-open-outline", "Open measurement files", self.open_files),
            ("chart-line", "Plot in its graphs", self.plot_selected),
            ("content-save-outline", "Save as JSON…", self.save_as),
            ("file-delimited-outline", "Export a table to CSV…", self.export),
            ("information-outline", "Details", self.details),
            ("folder-outline", "Show the data folder", self.open_folder),
            ("close", "Remove from the list (the file stays)", self.remove),
        ):
            button = QToolButton()
            button.setIcon(theme.icon(icon_name))
            button.setToolTip(tip)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.table.doubleClicked.connect(
            lambda index: index.column() != 2 and self.plot_selected()
        )
        layout.addWidget(self.table)

    def selected(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.measurement(r) for r in rows]

    def open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open measurements",
            str(self.session.store.root),
            "Measurements (*.json)",
        )
        for path in paths:
            try:
                measurement = self.model.open(path)
            except ValueError as e:
                QMessageBox.warning(self, "Open measurement", str(e))
                continue
            self.plot_requested.emit(measurement)

    def plot_selected(self) -> None:
        for measurement in self.selected():
            self.plot_requested.emit(measurement)

    def save_as(self) -> None:
        for measurement in self.selected():
            name = f"{measurement.id}_{measurement.procedure.replace('.', '_')}.json"
            path, _ = QFileDialog.getSaveFileName(
                self, "Save measurement", name, "JSON (*.json)"
            )
            if path:
                self.model.save(measurement, path)

    def export(self) -> None:
        for measurement in self.selected():
            tables = list(measurement.tables)
            if not tables:
                continue
            table = tables[0]
            if len(tables) > 1:
                table, ok = QInputDialog.getItem(
                    self, "Export CSV", "Table", tables, 0, False
                )
                if not ok:
                    continue
            name = f"{measurement.id}_{table}.csv"
            path, _ = QFileDialog.getSaveFileName(
                self, "Export CSV", name, "CSV (*.csv)"
            )
            if path:
                export_csv(measurement, table, path)

    def details(self) -> None:
        for measurement in self.selected()[:1]:
            DetailsDialog(measurement, self).exec()

    def open_folder(self) -> None:
        root = Path(self.session.store.root)
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root.resolve())))

    def remove(self) -> None:
        rows = sorted(
            {i.row() for i in self.table.selectionModel().selectedRows()}, reverse=True
        )
        for row in rows:
            if self.model.measurement(row).status != "running":
                self.model.remove(row)
