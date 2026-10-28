"""Lite mode: measurements are chosen and run from the bar on top.

The bar drives the ProcedureBox of the chosen measurement: comment, Start,
Stop, Abort when the box offers it, and its progress with the state. The box
lives in the Measurement dock (MeasurementHost), borrowed from the dock the
measurement has in Pro, so a run started in one mode goes on in the other and
choosing another measurement leaves a running one running.
"""

from typing import Dict, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme

# Groups of procedures in the bar's list, in this order
GROUP_ORDER = ("sis", "if", "two_sb", "monitor", "grid")


class RunBar(QWidget):
    chosen = Signal(str)  # procedure name
    parameters_requested = Signal()

    def __init__(self, procedures, parent=None):
        super().__init__(parent)
        self.box = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.combo = QComboBox()
        self.combo.setToolTip("Measurement to run")
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        groups: Dict[str, list] = {}
        for cls in procedures:
            groups.setdefault(cls.name.split(".")[0], []).append(cls)
        order = sorted(
            groups,
            key=lambda g: GROUP_ORDER.index(g)
            if g in GROUP_ORDER
            else len(GROUP_ORDER),
        )
        for group in order:
            if self.combo.count():
                self.combo.insertSeparator(self.combo.count())
            for cls in groups[group]:
                self.combo.addItem(
                    theme.icon(theme.procedure_icon_name(cls.name)),
                    cls.title or cls.name,
                    cls.name,
                )
        self.combo.activated.connect(
            lambda index: self.chosen.emit(self.combo.itemData(index))
        )
        layout.addWidget(self.combo)
        self.btnParameters = QToolButton()
        self.btnParameters.setIcon(theme.icon("tune-variant"))
        self.btnParameters.setToolTip("Devices and parameters of the measurement")
        self.btnParameters.clicked.connect(self.parameters_requested)
        layout.addWidget(self.btnParameters)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Comment")
        self.comment.setMinimumWidth(120)
        self.comment.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.comment.textEdited.connect(self.comment_edited)
        layout.addWidget(self.comment, 1)
        self.btnStart = QPushButton(theme.icon("play", "#111111"), "Start")
        self.btnStart.setProperty("accent", True)
        self.btnStart.clicked.connect(self.start)
        self.btnStop = QPushButton(theme.icon("stop"), "Stop")
        self.btnStop.clicked.connect(lambda: self.box and self.box.stop())
        self.btnAbort = QPushButton(theme.icon("lan-disconnect"), "Abort")
        self.btnAbort.setToolTip(
            "The measurement waits for a device that does not answer: break the "
            "connections of its devices"
        )
        self.btnAbort.clicked.connect(lambda: self.box and self.box.abort())
        self.btnAbort.hide()
        for button in (self.btnStart, self.btnStop, self.btnAbort):
            layout.addWidget(button)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        layout.addWidget(self.progress)

    def bind(self, box) -> None:
        """Drive this box (the chosen measurement) from now on."""
        if box is self.box:
            return
        if self.box is not None:
            try:
                self.box.status_changed.disconnect(self.sync)
            except (RuntimeError, TypeError):
                pass
        self.box = box
        box.status_changed.connect(self.sync)
        self.comment.setText(box.comment.text())
        index = self.combo.findData(box.procedure_class.name)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        self.sync()

    def chosen_name(self) -> Optional[str]:
        return self.combo.currentData()

    def comment_edited(self, text: str) -> None:
        if self.box is not None:
            self.box.comment.setText(text)

    def start(self) -> None:
        if self.box is not None:
            self.box.comment.setText(self.comment.text())
            self.box.start()

    def sync(self, *_) -> None:
        box = self.box
        if box is None:
            return
        running = box.ui_running
        self.btnStart.setEnabled(not running)
        self.btnStop.setEnabled(running)
        self.btnAbort.setVisible(running and box.abort_offered())
        self.progress.setRange(box.progress.minimum(), box.progress.maximum())
        self.progress.setValue(box.progress.value())
        text = box.status_text() if running else box.outcome
        self.progress.setFormat(text or "Idle")
        self.progress.setToolTip(box.state.text())


class MeasurementHost(QWidget):
    """Content of the Lite Measurement dock: the chosen measurement's widget,
    taken from its Pro dock (a DockBody) and given back on release."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.content: Optional[QWidget] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def take(self, body) -> QWidget:
        content = body.content()
        if content is self.content:
            return content
        self.release()
        if body.attached:
            body.set_open(False)
        self.layout().addWidget(content)
        content.box.set_controls_visible(False)
        content.show()
        self.content = content
        return content

    def release(self) -> None:
        content, self.content = self.content, None
        if content is None:
            return
        content.hide()  # first: a visible widget without a parent is a window
        self.layout().removeWidget(content)
        content.setParent(None)
        content.box.set_controls_visible(True)
