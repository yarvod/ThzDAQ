"""Lite mode: measurements are chosen and run from the bar on top.

The bar shows the run of the chosen measurement with RunControls in a row.
Its setup (devices, parameters, log) is in the Measurement dock
(MeasurementHost), the widget borrowed from the measurement's Pro dock, so a
run started in one mode goes on in the other and choosing another
measurement leaves a running one running.
"""

from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QToolButton, QVBoxLayout, QWidget
from thzdaq_api.measurements import ProcedureSummary

from thzdaq_gui import procedure_groups, theme
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.docks.measure import MeasureWidget
from thzdaq_gui.run_controls import Run, RunControls


class RunBar(QWidget):
    chosen = Signal(str)  # procedure name
    parameters_requested = Signal()

    def __init__(self, procedures: Iterable[ProcedureSummary], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.combo = QComboBox()
        self.combo.setToolTip("Measurement to run")
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        groups: Dict[str, List[ProcedureSummary]] = {}
        for procedure in sorted(
            procedures, key=lambda p: procedure_groups.rank(p.name)
        ):
            group = procedure_groups.group(procedure.name).key
            groups.setdefault(group, []).append(procedure)
        for group in groups:
            if self.combo.count():
                self.combo.insertSeparator(self.combo.count())
            for procedure in groups[group]:
                self.combo.addItem(
                    theme.icon(procedure_groups.group(procedure.name).icon),
                    procedure.title or procedure.name,
                    procedure.name,
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
        self.controls = RunControls(row=True)
        layout.addWidget(self.controls, 1)

    def show_run(self, procedure: str, run: Run) -> None:
        """The chosen measurement, driven from the bar from now on."""
        index = self.combo.findData(procedure)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        self.controls.bind(run)

    def chosen_name(self) -> Optional[str]:
        return self.combo.currentData()


class MeasurementHost(QWidget):
    """Content of the Lite Measurement dock: the chosen measurement's widget,
    taken from its Pro dock and given back on release."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.content: Optional[MeasureWidget] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def take(self, body: DockBody) -> MeasureWidget:
        content = body.lend()
        if content is self.content:
            return content
        self.release()
        self.layout().addWidget(content)
        content.show_controls(False)  # the bar on top has them
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
        content.show_controls(True)
