"""Processes dock: everything that runs now, stopped from one place.

A row per process (measurement, scan in a device dock, polling, chopper
rotation): status, progress, time, Stop and, when the process offers it,
Abort. A double click brings the dock of the process to the front.
"""

from typing import Dict

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.processes import Process

TITLE, STATUS, PROGRESS, TIME, ACTIONS = range(5)


def elapsed_text(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    )


class ProcessesWidget(QWidget):
    show_requested = Signal(str)  # the dock of a process
    count_changed = Signal(int)

    def __init__(self, processes, parent=None):
        super().__init__(parent)
        self.processes = processes
        self.rows: Dict[Process, QTreeWidgetItem] = {}
        self.bars: Dict[Process, QProgressBar] = {}
        self.aborts: Dict[Process, QToolButton] = {}
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        bar.addWidget(self.summary, 1)
        self.btnStopAll = QPushButton(theme.icon("stop"), "Stop all")
        self.btnStopAll.clicked.connect(processes.stop_all)
        bar.addWidget(self.btnStopAll)
        layout.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Process", "Status", "Progress", "Time", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(STATUS, QHeaderView.Interactive)
        header.setSectionResizeMode(PROGRESS, QHeaderView.Fixed)
        header.setSectionResizeMode(TIME, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(ACTIONS, QHeaderView.ResizeToContents)
        header.resizeSection(STATUS, 170)
        header.resizeSection(PROGRESS, 120)
        self.tree.itemDoubleClicked.connect(lambda item, _: self.show_item(item))
        layout.addWidget(self.tree, 1)
        # Time runs on even when nothing else changes
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self.tick)
        processes.added.connect(self.add)
        processes.removed.connect(self.remove)
        for process in processes.items:
            self.add(process)
        self.show_count()

    def add(self, process: Process) -> None:
        item = QTreeWidgetItem([process.title, "", "", "", ""])
        item.setIcon(TITLE, theme.icon(process.icon))
        item.setToolTip(TITLE, f"{process.title}\nDouble click: show it")
        item.setForeground(STATUS, QColor(theme.MUTED))
        self.tree.addTopLevelItem(item)
        bar = QProgressBar()
        bar.setMaximumHeight(16)
        bar.setTextVisible(True)
        self.tree.setItemWidget(item, PROGRESS, bar)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        stop = QToolButton()
        stop.setIcon(theme.icon("stop"))
        stop.setToolTip("Stop")
        stop.clicked.connect(process.stop)
        abort = QToolButton()
        abort.setIcon(theme.icon("lan-disconnect"))
        abort.setToolTip(
            "Abort: it waits for a device that does not answer, break the "
            "connections of its devices"
        )
        abort.clicked.connect(process.abort)
        show = QToolButton()
        show.setIcon(theme.icon("eye"))
        show.setToolTip("Show its dock")
        show.clicked.connect(lambda: self.show_process(process))
        for button in (show, stop, abort):
            row.addWidget(button)
        self.tree.setItemWidget(item, ACTIONS, buttons)
        self.rows[process] = item
        self.bars[process] = bar
        self.aborts[process] = abort
        process.changed.connect(lambda p=process: self.refresh(p))
        self.refresh(process)
        self.show_count()

    def remove(self, process: Process) -> None:
        item = self.rows.pop(process, None)
        self.bars.pop(process, None)
        self.aborts.pop(process, None)
        if item is not None:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.show_count()

    def refresh(self, process: Process) -> None:
        item = self.rows.get(process)
        if item is None:
            return
        item.setText(STATUS, process.status)
        item.setToolTip(STATUS, process.status)
        item.setText(TIME, elapsed_text(process.elapsed()))
        bar = self.bars[process]
        if process.progress is None:
            bar.setRange(0, 0)  # busy: no end known
        else:
            done, total = process.progress
            bar.setRange(0, max(total, 1))
            bar.setValue(min(done, total))
        self.aborts[process].setVisible(process.can_abort)

    def tick(self) -> None:
        for process, item in self.rows.items():
            item.setText(TIME, elapsed_text(process.elapsed()))

    def show_count(self) -> None:
        count = len(self.rows)
        self.summary.setText(f"{count} running" if count else "Nothing is running")
        self.btnStopAll.setEnabled(bool(count))
        if count:
            self.clock.start()
        else:
            self.clock.stop()
        self.count_changed.emit(count)

    def show_item(self, item: QTreeWidgetItem) -> None:
        for process, row in self.rows.items():
            if row is item:
                self.show_process(process)

    def show_process(self, process: Process) -> None:
        self.show_requested.emit(process.dock)
        process.show()
