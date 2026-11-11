"""The bar on top: a measurement chosen, started and stopped from there.

The bar shows the run of the chosen measurement with RunControls in a row;
the dock of the measurement shows the same run with its own controls, under
its devices and parameters. The settings button shows that dock. Choosing
another measurement leaves a running one running.
"""

from typing import Callable, Dict, Iterable, List, Optional

from PySide6.QtCore import QSettings, QSignalBlocker, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSizePolicy, QToolButton, QWidget
from thzdaq_api.measurements import ProcedureSummary
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE, current_name

from thzdaq_gui import procedure_groups, theme
from thzdaq_gui.run_controls import Run, RunControls
from thzdaq_gui.settings import CHOSEN_MEASUREMENT

DEFAULT_MEASUREMENT = CURRENT_VS_VOLTAGE
COMMENT_WIDTH = 320  # at least: the comment takes the free width of the bar


class RunBar(QWidget):
    dock_requested = Signal(str)  # the procedure whose dock to show

    def __init__(
        self,
        procedures: Iterable[ProcedureSummary],
        run_of: Callable[[str], Optional[Run]],
        settings: QSettings,
        parent=None,
    ):
        """run_of(procedure): the run its dock shows; None: no such dock."""
        super().__init__(parent)
        self.run_of = run_of
        self.settings = settings
        # The free width of the toolbar goes to the comment
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.combo = QComboBox()
        self.combo.setToolTip("Measurement to run")
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.set_procedures(procedures)
        if not self.select(current_name(settings.value(CHOSEN_MEASUREMENT) or "")):
            self.select(DEFAULT_MEASUREMENT)
        self.combo.activated.connect(
            lambda index: self.choose(self.combo.itemData(index))
        )
        layout.addWidget(self.combo)
        self.btnParameters = QToolButton()
        self.btnParameters.setIcon(theme.icon("tune-variant"))
        self.btnParameters.setToolTip(
            "Devices and parameters of the measurement: its dock"
        )
        self.btnParameters.clicked.connect(
            lambda: self.dock_requested.emit(self.chosen_name())
        )
        layout.addWidget(self.btnParameters)
        self.controls = RunControls(row=True)
        self.controls.comment.setMinimumWidth(COMMENT_WIDTH)
        layout.addWidget(self.controls, 1)

    def set_procedures(self, procedures: Iterable[ProcedureSummary]) -> None:
        """The measurements to choose from, by group (the bench's own last);
        the one chosen stays chosen while it is among them, else the default
        is chosen."""
        chosen = self.combo.currentData()
        groups: Dict[str, List[ProcedureSummary]] = {}
        for procedure in sorted(
            procedures, key=lambda p: procedure_groups.rank(p.name)
        ):
            group = procedure_groups.group(procedure.name).key
            groups.setdefault(group, []).append(procedure)
        with QSignalBlocker(self.combo):
            self.combo.clear()
            for group in groups:
                if self.combo.count():
                    self.combo.insertSeparator(self.combo.count())
                for procedure in groups[group]:
                    self.combo.addItem(
                        theme.icon(procedure_groups.group(procedure.name).icon),
                        procedure.title or procedure.name,
                        procedure.name,
                    )
        if chosen is not None and not self.select(chosen):
            self.choose(DEFAULT_MEASUREMENT)

    def select(self, procedure: str) -> bool:
        """The procedure in the list; False: it is not there (the first is)."""
        index = self.combo.findData(procedure)
        with QSignalBlocker(self.combo):
            self.combo.setCurrentIndex(max(index, 0))
        return index >= 0

    def choose(self, procedure: str) -> None:
        """Run this measurement from the bar from now on; remembered."""
        self.select(procedure)
        self.show_chosen()
        self.settings.setValue(CHOSEN_MEASUREMENT, self.chosen_name())

    def show_chosen(self) -> None:
        """The controls drive the run of the chosen measurement's dock."""
        run = self.run_of(self.chosen_name())
        if run is not None:
            self.controls.bind(run)

    def chosen_name(self) -> Optional[str]:
        return self.combo.currentData()
