"""The bar on top: the measurement chosen, its parameters, started and stopped.

Left to right: the list of measurements (by group, the bench's own last,
New measurement… and From an example…), the settings button whose drop-down
shows the chosen one's devices and parameters, then its run (RunControls in
a row: graphs, comment, Start, Check, Stop, progress). A measurement that
runs turns its icon in the list, and on the list's button while it is the
one chosen; choosing another leaves a running one running.

The bar is where measurements are found (Ctrl+K, Processes): showing one
chooses it and opens its parameters.
"""

from typing import Callable, Dict, Iterable, List, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QStyle,
    QToolButton,
    QWidget,
)
from thzdaq_api import examples
from thzdaq_api.measurements import ProcedureSummary
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE, current_name

from thzdaq_gui import procedure_groups, theme
from thzdaq_gui.dock_names import MEASURE, dock_name, key_of
from thzdaq_gui.measure_forms import MeasureForms
from thzdaq_gui.navigator import BEHIND, CLOSED, FRONT, DockEntry
from thzdaq_gui.popup import DropDown
from thzdaq_gui.run_controls import RunControls
from thzdaq_gui.settings import CHOSEN_MEASUREMENT

DEFAULT_MEASUREMENT = CURRENT_VS_VOLTAGE
# The comment's: 18 % less than it took of a window 1500 px wide (427 px)
# when it took the bar's free width; that width stays free now
COMMENT_WIDTH = 350
SECTION = "Measures"  # of the finder


class RunBar(QWidget):
    def __init__(
        self,
        procedures: Iterable[ProcedureSummary],
        measures: MeasureForms,
        settings: QSettings,
        new_measurement: Callable[[], None],
        from_example: Callable[[str], None],
        parent=None,
    ):
        """new_measurement(), from_example(name): a measurement of the
        bench's own begun as a script."""
        super().__init__(parent)
        self.measures = measures
        self.settings = settings
        self.new_measurement = new_measurement
        self.from_example = from_example
        self.procedures: List[ProcedureSummary] = []
        self.items: Dict[str, QAction] = {}  # by procedure
        self.chosen: Optional[str] = None
        self.wanted: Optional[str] = None  # to choose once it is listed
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.select = QToolButton()
        self.select.setProperty("select", True)
        self.select.setToolTip("Measurement to run")
        self.select.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.select.setPopupMode(QToolButton.InstantPopup)
        self.list = QMenu(self.select)
        self.select.setMenu(self.list)
        self.list_spinner = theme.Spinner(self.list)
        self.select_spinner = theme.Spinner(self.select)
        layout.addWidget(self.select)
        self.btnParameters = QToolButton()
        self.btnParameters.setIcon(theme.icon("cog-outline"))
        self.btnParameters.setToolTip("Devices and parameters of the measurement")
        self.btnParameters.setCheckable(True)
        self.btnParameters.clicked.connect(self.toggle_parameters)
        layout.addWidget(self.btnParameters)
        self.parameters = DropDown(self.btnParameters)
        self.parameters.visibility_changed.connect(self.btnParameters.setChecked)
        self.controls = RunControls(row=True)
        self.controls.comment.setFixedWidth(COMMENT_WIDTH)
        layout.addWidget(self.controls)
        layout.addStretch(1)
        measures.running_changed.connect(self.show_running)
        self.set_procedures(procedures)
        if not self.select_name(current_name(settings.value(CHOSEN_MEASUREMENT) or "")):
            self.select_name(DEFAULT_MEASUREMENT)

    # The list
    def set_procedures(self, procedures: Iterable[ProcedureSummary]) -> None:
        """The measurements to choose from, by group (the bench's own last),
        then those to begin; the one chosen stays chosen while it is among
        them, else the default is chosen."""
        self.procedures = sorted(
            procedures, key=lambda p: procedure_groups.rank(p.name)
        )
        self.list.clear()
        self.items.clear()
        group = None
        for procedure in self.procedures:
            if group is not None and procedure_groups.group(procedure.name) != group:
                self.list.addSeparator()
            group = procedure_groups.group(procedure.name)
            item = self.list.addAction(procedure.title or procedure.name)
            item.setData(procedure.name)
            item.setToolTip(procedure.description)
            item.triggered.connect(
                lambda _=False, name=procedure.name: self.choose(name)
            )
            self.items[procedure.name] = item
            self.show_icon(procedure.name)
        self.list.addSeparator()
        begin = self.list.addAction(theme.icon("plus"), "New measurement…")
        begin.setToolTip("A measurement of the bench's own: a script")
        begin.triggered.connect(lambda: self.new_measurement())
        from_example = self.list.addMenu(
            theme.icon("book-open-outline"), "From an example…"
        )
        for example in examples.examples():
            action = from_example.addAction(example.title)
            action.setToolTip(example.about)
            action.triggered.connect(
                lambda _=False, name=example.name: self.from_example(name)
            )
        self.fit_select()
        if self.wanted in self.items:
            self.choose(self.wanted)
        elif self.chosen is not None and not self.select_name(self.chosen):
            self.choose(DEFAULT_MEASUREMENT)

    def fit_select(self) -> None:
        """As wide as its longest title: the bar does not move as one is chosen."""
        metrics = self.select.fontMetrics()
        text = max(
            (metrics.horizontalAdvance(p.title or p.name) for p in self.procedures),
            default=0,
        )
        icon = self.select.style().pixelMetric(QStyle.PM_SmallIconSize)
        self.select.setMinimumWidth(text + icon + 44)

    def show_icon(self, procedure: str) -> None:
        """Its group's, or turning while it runs."""
        running = procedure in self.measures.running()
        icon = theme.icon(procedure_groups.group(procedure).icon)
        item = self.items.get(procedure)
        if item is not None:
            item.setIcon(self.list_spinner.icon if running else icon)
        if procedure == self.chosen:
            self.select.setIcon(self.select_spinner.icon if running else icon)

    def show_running(self, procedure: str, running: bool) -> None:
        self.show_icon(procedure)
        self.list_spinner.run(bool(self.measures.running()))
        self.select_spinner.run(self.chosen in self.measures.running())

    # The chosen one
    def select_name(self, procedure: str) -> bool:
        """The procedure shown chosen; False: it is not in the list (the
        first is)."""
        item = self.items.get(procedure)
        if item is None and self.procedures:
            item = self.items[self.procedures[0].name]
        if item is None:
            return False
        previous, self.chosen = self.chosen, item.data()
        for name in (previous, self.chosen):
            if name in self.items:
                font = QFont(self.items[name].font())
                font.setBold(name == self.chosen)
                self.items[name].setFont(font)
        self.select.setText(item.text())
        self.select.setToolTip(f"Measurement to run: {item.text()}")
        self.show_icon(self.chosen)
        self.select_spinner.run(self.chosen in self.measures.running())
        return self.chosen == procedure

    def choose(self, procedure: str) -> None:
        """Run this measurement from the bar from now on; remembered."""
        self.wanted = None
        self.select_name(procedure)
        self.show_chosen()
        self.settings.setValue(CHOSEN_MEASUREMENT, self.chosen)

    def want(self, procedure: str) -> None:
        """Chosen now when it is in the list, else as soon as it is (a script
        just written is listed once the daemon has described it); choosing
        another first cancels it."""
        if procedure not in self.items:
            self.wanted = procedure
        elif procedure == self.chosen:
            self.wanted = None
        else:
            self.choose(procedure)

    def show_chosen(self) -> None:
        """The controls drive the run of the chosen measurement's form, and
        the drop-down shows its form."""
        form = self.measures.form(self.chosen) if self.chosen else None
        if form is None:
            return
        self.controls.bind(form.box)
        self.parameters.show_widget(form)

    def chosen_name(self) -> Optional[str]:
        return self.chosen

    def toggle_parameters(self) -> None:
        self.show_chosen()
        self.parameters.toggle()

    def show_parameters(self) -> None:
        self.show_chosen()
        self.parameters.open()

    # Measurements as the finder and Processes show them: measure:<procedure>
    def __contains__(self, name: str) -> bool:
        return key_of(name, MEASURE) in self.items

    def listed(self) -> List[DockEntry]:
        entries = []
        for procedure in self.procedures:
            group = procedure_groups.group(procedure.name)
            entries.append(
                DockEntry(
                    dock_name(MEASURE, procedure.name),
                    procedure.title or procedure.name,
                    SECTION,
                    theme.icon(group.icon),
                    group.title,
                    procedure.name,
                )
            )
        return entries

    def state(self, name: str) -> str:
        """FRONT: its parameters are open; BEHIND: it is chosen."""
        if key_of(name, MEASURE) != self.chosen:
            return CLOSED
        return FRONT if self.parameters.isVisible() else BEHIND

    def show(self, name: str) -> None:
        """Chosen, with its parameters open."""
        self.choose(key_of(name, MEASURE))
        self.show_parameters()

    def toggle(self, name: str) -> None:
        if self.state(name) == FRONT:
            self.parameters.hide()
        else:
            self.show(name)
