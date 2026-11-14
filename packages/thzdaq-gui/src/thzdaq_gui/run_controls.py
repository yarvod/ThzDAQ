"""Comment, Start/Stop/Abort, graphs and progress of a run: a view of its
RunStatus.

A run (ProcedureBox) keeps how it goes in a RunStatus and tells every change;
RunControls show it and call the run back. The bar on top shows the chosen
measurement's run in a row; a scan in a device dock has its own controls in
a column. They read the run, never each other.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from thzdaq_api.ui import ControlState

from thzdaq_gui import theme
from thzdaq_gui.dock_names import (
    ABORT,
    CHECK,
    COMMENT,
    GRAPHS,
    RUN,
    START,
    STOP,
    dock_name,
)

# The controls by their names (run:start), as people read them
TITLES = {
    GRAPHS: "Graphs",
    COMMENT: "Comment",
    START: "Start",
    CHECK: "Check",
    STOP: "Stop",
    ABORT: "Abort",
}

IDLE = "Idle"
CONNECTING = "Connecting to devices..."
RUNNING = "Running"
STOPPING = "Stopping..."


@dataclass(frozen=True)
class RunStatus:
    running: bool = False
    state: str = IDLE  # what the run does now: CONNECTING, RUNNING, STOPPING
    done: int = 0
    total: Optional[int] = 1  # steps; None: no end known
    outcome: str = ""  # how the last run ended: "completed #12"
    can_abort: bool = False  # it waits for a device that does not answer

    def line(self) -> str:
        """One line: "Running 42 %", "completed #12"."""
        if not self.running:
            return self.outcome
        if self.total:
            return f"{self.state} {round(100 * self.done / self.total)} %"
        return self.state


class Run(Protocol):
    """What RunControls drive (ProcedureBox); its signals status_changed and
    comment_changed tell every change."""

    comment: str

    def status(self) -> RunStatus:
        ...

    def set_comment(self, text: str) -> None:
        ...

    def start(self) -> None:
        ...

    def check(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def abort(self) -> None:
        ...

    def show_graphs(self) -> None:
        ...


class RunControls(QWidget):
    """row: one line for the bar on top, the graphs first as an icon, the
    state inside the progress bar; otherwise a column under the setup of a
    scan in a device dock."""

    def __init__(self, row: bool = False, parent=None):
        super().__init__(parent)
        self.run: Optional[Run] = None
        self.comment = QLineEdit()
        self.comment.setPlaceholderText(TITLES[COMMENT])
        self.comment.textEdited.connect(self.comment_edited)
        self.btnStart = QPushButton(theme.icon("play", "#111111"), TITLES[START])
        self.btnStart.setProperty("accent", True)
        self.btnStart.clicked.connect(lambda: self.run and self.run.start())
        self.btnCheck = QPushButton(
            theme.icon("clipboard-check-outline"), TITLES[CHECK]
        )
        self.btnCheck.setToolTip(
            "Would it start? Parameters, devices, their limits and who uses them, "
            "checked without starting"
        )
        self.btnCheck.clicked.connect(lambda: self.run and self.run.check())
        self.btnStop = QPushButton(theme.icon("stop"), TITLES[STOP])
        self.btnStop.setEnabled(False)
        self.btnStop.clicked.connect(lambda: self.run and self.run.stop())
        self.btnAbort = QPushButton(theme.icon("lan-disconnect"), TITLES[ABORT])
        self.btnAbort.setToolTip(
            "The measurement waits for a device that does not answer: break the "
            "connections of its devices (they reconnect on the next command)"
        )
        self.btnAbort.clicked.connect(lambda: self.run and self.run.abort())
        self.btnAbort.hide()
        self.btnGraphs = QPushButton(theme.icon("chart-line"), TITLES[GRAPHS])
        self.btnGraphs.setToolTip("Show the graphs this measurement draws")
        self.btnGraphs.clicked.connect(lambda: self.run and self.run.show_graphs())
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        # By their names, for agents (thzdaq_api.ui)
        self.named: Dict[str, QWidget] = {
            GRAPHS: self.btnGraphs,
            COMMENT: self.comment,
            START: self.btnStart,
            CHECK: self.btnCheck,
            STOP: self.btnStop,
            ABORT: self.btnAbort,
        }
        buttons = (self.btnStart, self.btnCheck, self.btnStop, self.btnAbort)
        self.state: Optional[QLabel] = None
        if row:
            layout = QHBoxLayout(self)
            layout.setSpacing(4)
            self.btnGraphs.setText("")
            layout.addWidget(self.btnGraphs)
            self.comment.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            layout.addWidget(self.comment)
            for button in buttons:
                layout.addWidget(button)
            self.progress.setFixedWidth(200)
            layout.addWidget(self.progress)
        else:
            layout = QVBoxLayout(self)
            layout.addWidget(self.comment)
            line = QHBoxLayout()
            for button in (*buttons, self.btnGraphs):
                line.addWidget(button)
            layout.addLayout(line)
            self.state = QLabel(IDLE)
            self.state.setProperty("role", "muted")
            layout.addWidget(self.state)
            layout.addWidget(self.progress)
        layout.setContentsMargins(0, 0, 0, 0)

    def bind(self, run) -> None:
        """Show this run and drive it from now on."""
        if run is self.run:
            return
        if self.run is not None:
            try:
                self.run.status_changed.disconnect(self.refresh)
                self.run.comment_changed.disconnect(self.show_comment)
            except (RuntimeError, TypeError):  # the run is gone
                pass
        self.run = run
        run.status_changed.connect(self.refresh)
        run.comment_changed.connect(self.show_comment)
        self.show_comment(run.comment)
        self.refresh()

    def __contains__(self, key: str) -> bool:
        return key in self.named

    def control(self, key: str) -> Optional[QWidget]:
        """A control shown now, by its key (start); None for another."""
        widget = self.named.get(key)
        return widget if widget is not None and not widget.isHidden() else None

    def described(self) -> List[ControlState]:
        """The controls shown now, as run:<key>, and whether they take a click."""
        return [
            ControlState(dock_name(RUN, key), TITLES[key], widget.isEnabled())
            for key, widget in self.named.items()
            if not widget.isHidden()
        ]

    def comment_edited(self, text: str) -> None:
        if self.run is not None:
            self.run.set_comment(text)

    def show_comment(self, text: str) -> None:
        if self.comment.text() != text:  # the cursor stays where one types
            self.comment.setText(text)

    def refresh(self, *_) -> None:
        if self.run is None:
            return
        status = self.run.status()
        self.btnStart.setEnabled(not status.running)
        self.btnCheck.setEnabled(not status.running)
        self.btnStop.setEnabled(status.running)
        self.btnAbort.setVisible(status.running and status.can_abort)
        if status.total is None:
            self.progress.setRange(0, 0)  # busy
        else:
            self.progress.setRange(0, status.total)
            self.progress.setValue(min(status.done, status.total))
        if self.state is not None:
            self.state.setText(status.state)
        else:
            self.progress.setFormat(status.line() or IDLE)
            self.progress.setToolTip(status.state)
