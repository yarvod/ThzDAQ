"""Comment, Start/Stop/Abort and progress of a run: a view of its RunStatus.

A run (ProcedureBox) keeps how it goes in a RunStatus and tells every change;
RunControls show it and call the run back. Every measurement dock has its own
controls; in Lite the bar on top shows the chosen run with another one, in a
row. Both read the run, never each other.
"""

from dataclasses import dataclass
from typing import Optional, Protocol

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

from thzdaq_gui import theme

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

    def stop(self) -> None:
        ...

    def abort(self) -> None:
        ...


class RunControls(QWidget):
    """row: one line for the bar on top, the state inside the progress bar;
    otherwise a column under the setup in a dock."""

    def __init__(self, row: bool = False, parent=None):
        super().__init__(parent)
        self.run: Optional[Run] = None
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Comment")
        self.comment.textEdited.connect(self.comment_edited)
        self.btnStart = QPushButton(theme.icon("play", "#111111"), "Start")
        self.btnStart.setProperty("accent", True)
        self.btnStart.clicked.connect(lambda: self.run and self.run.start())
        self.btnStop = QPushButton(theme.icon("stop"), "Stop")
        self.btnStop.setEnabled(False)
        self.btnStop.clicked.connect(lambda: self.run and self.run.stop())
        self.btnAbort = QPushButton(theme.icon("lan-disconnect"), "Abort")
        self.btnAbort.setToolTip(
            "The measurement waits for a device that does not answer: break the "
            "connections of its devices (they reconnect on the next command)"
        )
        self.btnAbort.clicked.connect(lambda: self.run and self.run.abort())
        self.btnAbort.hide()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        buttons = (self.btnStart, self.btnStop, self.btnAbort)
        self.state: Optional[QLabel] = None
        if row:
            layout = QHBoxLayout(self)
            layout.setSpacing(4)
            self.comment.setMinimumWidth(120)
            self.comment.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout.addWidget(self.comment, 1)
            for button in buttons:
                layout.addWidget(button)
            self.progress.setFixedWidth(200)
            layout.addWidget(self.progress)
        else:
            layout = QVBoxLayout(self)
            layout.addWidget(self.comment)
            line = QHBoxLayout()
            for button in buttons:
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
