from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.data.store import read_dataset

COLUMNS = ("Started", "Procedure", "Status", "Records", "Comment")


class DataPanel(QWidget):
    """Datasets of the data folder; double click opens one in the plots."""

    dataset_opened = Signal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.folder = QLabel()
        top.addWidget(self.folder, 1)
        self.btnRefresh = QPushButton("Refresh")
        self.btnRefresh.clicked.connect(self.refresh)
        top.addWidget(self.btnRefresh)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.open_row)
        layout.addWidget(self.table)
        self.paths = []
        session.runner.finished.connect(lambda _: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        self.folder.setText(f"Data: {self.session.store.root.resolve()}")
        self.paths = list(reversed(self.session.store.paths()))
        self.table.setRowCount(len(self.paths))
        for row, path in enumerate(self.paths):
            try:
                dataset = read_dataset(path)
                cells = (
                    dataset.started.replace("T", " ")[:19],
                    dataset.procedure,
                    dataset.status,
                    ", ".join(f"{k}: {len(v)}" for k, v in dataset.streams.items()),
                    dataset.comment,
                )
            except (OSError, ValueError) as e:
                cells = ("?", path.name, f"unreadable: {e}", "", "")
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))

    def open_row(self, row: int, _column: int = 0) -> None:
        self.dataset_opened.emit(read_dataset(self.paths[row]))
