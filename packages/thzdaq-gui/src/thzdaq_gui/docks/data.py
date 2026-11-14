"""Data dock: measurements of the session and opened files, as the old table.

Every measurement is saved to data/<date>/ of its workspace as it runs; here
it can be commented, plotted again, saved elsewhere as JSON or exported to
CSV. Measurements of other workspaces show on asking (Others). The file
dialogs start in the folder used last (Session.folders).
"""

import json
from pathlib import Path

import msgspec

from PySide6.QtCore import QSortFilterProxyModel, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
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
from thzdaq_api.measurement_file import SCRIPT, RUNNING, dumps, export_csv
from thzdaq_api.sessions import ScriptSource

from thzdaq_gui import theme
from thzdaq_gui.folders import MEASUREMENTS

SCRIPT_TITLE = "The script of a measurement"


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


class Shown(QSortFilterProxyModel):
    """The window's own measurements, and those of other workspaces with
    others on."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.others = False
        self.setSourceModel(model)
        model.session.workspace.changed.connect(self.invalidateFilter)

    def show_others(self, on: bool) -> None:
        self.others = on
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent) -> bool:
        return self.others or self.sourceModel().here(row)


class DataWidget(QWidget):
    plot_requested = Signal(object)  # Measurement
    script_requested = Signal(str, str)  # the script it ran: a title, its text

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.model = session.measurements
        self.shown = Shown(self.model, self)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        for icon_name, tip, slot in (
            ("folder-open-outline", "Open measurement files", self.open_files),
            ("chart-line", "Plot in its graphs", self.plot_selected),
            ("content-save-outline", "Save as JSON…", self.save_as),
            ("file-delimited-outline", "Export a table to CSV…", self.export),
            ("information-outline", "Details", self.details),
            ("language-python", "The script that measured it", self.script),
            ("folder-outline", "Show the data folder", self.open_folder),
            ("close", "Remove from the list (the file stays)", self.remove),
        ):
            button = QToolButton()
            button.setIcon(theme.icon(icon_name))
            button.setToolTip(tip)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch()
        self.othersButton = QToolButton()
        self.othersButton.setIcon(theme.icon("folder-multiple-outline"))
        self.othersButton.setText("Others")
        self.othersButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.othersButton.setToolTip("Also measurements of other workspaces")
        self.othersButton.setCheckable(True)
        self.othersButton.toggled.connect(self.shown.show_others)
        bar.addWidget(self.othersButton)
        layout.addLayout(bar)
        self.table = QTableView()
        self.table.setModel(self.shown)
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

    def selected_rows(self):
        """Rows of the model the selection shows, top first."""
        return sorted(
            {
                self.shown.mapToSource(index).row()
                for index in self.table.selectionModel().selectedRows()
            }
        )

    def selected(self):
        return [self.model.measurement(row) for row in self.selected_rows()]

    def open_files(self) -> None:
        paths = self.session.folders.open_paths(
            self, MEASUREMENTS, "Open measurements", "Measurements (*.json)"
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
            path = self.session.folders.save_path(
                self, MEASUREMENTS, "Save measurement", name, "JSON (*.json)"
            )
            if path:
                self.model.save_copy(measurement, path)

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
            path = self.session.folders.save_path(
                self, MEASUREMENTS, "Export CSV", name, "CSV (*.csv)"
            )
            if path:
                export_csv(measurement, table, path)

    def script(self) -> None:
        """The text it ran as it was then, in the editor: titled by the
        measurement, to be saved into the library."""
        for measurement in self.selected()[:1]:
            kept = measurement.metadata.get(SCRIPT)
            if not kept:
                QMessageBox.information(
                    self,
                    SCRIPT_TITLE,
                    "No script measured it: its text is kept only with the "
                    "measurements of a script (lab.measurement) and of the "
                    "bench's own.",
                )
                return
            source = msgspec.convert(kept, ScriptSource)
            self.script_requested.emit(
                f"#{measurement.id} {Path(source.path).name}", source.text
            )

    def details(self) -> None:
        for measurement in self.selected()[:1]:
            DetailsDialog(measurement, self).exec()

    def open_folder(self) -> None:
        root = self.session.data_root
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root.resolve())))

    def remove(self) -> None:
        for row in reversed(self.selected_rows()):
            if self.model.items[row].status != RUNNING:
                self.model.remove(row)
