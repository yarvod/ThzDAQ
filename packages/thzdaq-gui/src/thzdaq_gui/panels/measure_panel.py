from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.data.dataset import COMPLETED
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.registry import get_procedure, list_procedures

from thzdaq_gui.forms import ParameterForm, RoleMappingForm


class MeasurePanel(QWidget):
    """Pick a procedure, fill its form, map roles, run and stop."""

    run_started = Signal(object)  # procedure instance
    run_finished = Signal(object)  # dataset

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)

        self.procedureCombo = QComboBox()
        for cls in list_procedures():
            self.procedureCombo.addItem(f"{cls.title}  ({cls.name})", cls.name)
        self.procedureCombo.currentIndexChanged.connect(self.select_procedure)
        layout.addWidget(self.procedureCombo)

        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.form = ParameterForm()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form)
        layout.addWidget(scroll, 3)

        rolesBox = QGroupBox("Roles")
        rolesLayout = QVBoxLayout(rolesBox)
        self.roles = RoleMappingForm()
        rolesLayout.addWidget(self.roles)
        self.btnRoles = QPushButton("Update roles from parameters")
        self.btnRoles.clicked.connect(self.update_roles)
        rolesLayout.addWidget(self.btnRoles)
        layout.addWidget(rolesBox)

        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Comment")
        layout.addWidget(self.comment)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.btnStart = QPushButton("Start")
        self.btnStart.clicked.connect(self.start)
        self.btnStop = QPushButton("Stop")
        self.btnStop.clicked.connect(session.runner.cancel)
        self.btnStop.setEnabled(False)
        buttons.addWidget(self.btnStart)
        buttons.addWidget(self.btnStop)
        layout.addLayout(buttons)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        layout.addWidget(self.log, 1)

        runner = session.runner
        runner.progress.connect(self.show_progress)
        runner.log.connect(self.log.appendPlainText)
        runner.failed.connect(self.on_failed)
        runner.finished.connect(self.on_finished)
        runner.running_changed.connect(self.set_running)
        session.station_changed.connect(lambda _: self.update_roles())
        self.select_procedure()

    def current_class(self):
        name = self.procedureCombo.currentData()
        return get_procedure(name) if name else None

    def select_procedure(self) -> None:
        cls = self.current_class()
        if cls is None:
            return
        self.description.setText(cls.description)
        self.form.set_procedure(cls)
        self.update_roles()

    def station_roles(self):
        station = self.session.station
        return list(station.config.roles) if station is not None else []

    def update_roles(self) -> None:
        cls = self.current_class()
        if cls is None:
            return
        try:
            required = self.form.procedure().roles()
        except ProcedureError:
            required = cls.requires
        self.roles.set_roles(required, self.station_roles())

    def start(self) -> None:
        if self.session.station is None:
            QMessageBox.warning(self, "No station", "Open a station profile first")
            return
        try:
            procedure = self.form.procedure()
        except ProcedureError as e:
            QMessageBox.warning(self, "Invalid parameters", str(e))
            return
        self.roles.set_roles(procedure.roles(), self.station_roles())
        missing = self.roles.unmapped()
        if missing:
            QMessageBox.warning(
                self, "Roles", f"Choose station roles for: {', '.join(missing)}"
            )
            return
        self.progress.setRange(0, procedure.estimate_steps() or 0)
        self.progress.setValue(0)
        self.log.appendPlainText(f"▶ {procedure.title}")
        self.run_started.emit(procedure)
        self.session.runner.start(
            self.session.station,
            self.session.store,
            procedure,
            self.roles.mapping(),
            self.comment.text(),
        )

    def show_progress(self, done: int, total) -> None:
        if total:
            self.progress.setRange(0, total)
        self.progress.setValue(done)

    def set_running(self, running: bool) -> None:
        self.btnStart.setEnabled(not running)
        self.btnStop.setEnabled(running)
        self.procedureCombo.setEnabled(not running)

    def on_failed(self, message: str) -> None:
        self.log.appendPlainText(f"✖ {message}")
        QMessageBox.critical(self, "Measurement not started", message)

    def on_finished(self, dataset) -> None:
        line = f"■ {dataset.status}"
        if dataset.error:
            line += f": {dataset.error}"
        if dataset.metadata.get("path"):
            line += f"\n  {dataset.metadata['path']}"
        self.log.appendPlainText(line)
        if dataset.status != COMPLETED and dataset.error:
            QMessageBox.warning(self, "Measurement failed", dataset.error)
        self.run_finished.emit(dataset)
