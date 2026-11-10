"""The dock of one of the bench's own measurements (custom.<name>): as a
built-in one's (devices, its form, Start/Stop, its graphs), with its script a
click away (Code), where each plot it declares is drawn (Graphs: a graph of
its own or one of the window's, into= of the script first) and what the
script printed during the last run (Output).

Saving the script describes it anew: the form follows (after the run, when
one goes on); a script that cannot be described shows why, and its Code.
"""

from typing import Callable, Dict, Optional, Tuple

import msgspec
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.errors import LabError
from thzdaq_api.measurements import PlotInfo, ProcedureInfo, ProcedureSummary

from thzdaq_gui import theme
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.docks.measure import MeasureWidget, ProcedureBox
from thzdaq_gui.script_output import ScriptOutput
from thzdaq_gui.settings import graph_choice_key, settings

# Opens the script of a measurement (its procedure) at a line (0: where it was)
OpenCode = Callable[[str, int], None]


def last_line(error: str) -> str:
    lines = error.strip().splitlines()
    return lines[-1] if lines else error


class CustomBox(ProcedureBox):
    """A script that cannot be described has no form: the box waits for it.
    Its declared plots go where the dock chose (into)."""

    into: Callable[[PlotInfo], Optional[str]] = staticmethod(lambda plot: plot.into)

    def described(self) -> ProcedureInfo:
        try:
            return super().described()
        except LabError:
            return ProcedureInfo(self.procedure, self.procedure, "", (), (), ())

    def chosen_plots(self, plots):
        return tuple(msgspec.structs.replace(p, into=self.into(p)) for p in plots)


class GraphChoice(QWidget):
    """Where each declared plot is drawn: a graph of its own, or one of the
    window's; remembered, the script's into= first."""

    OWN = "A graph of its own"

    def __init__(self, procedure: str, hub, parent=None):
        super().__init__(parent)
        self.procedure = procedure
        self.hub = hub
        self.form = QFormLayout(self)
        self.combos: Dict[str, QComboBox] = {}  # by the plot's key
        self.plots: Tuple[PlotInfo, ...] = ()
        hub.titles_added.connect(lambda _: self.show_plots(self.plots))
        hub.graph_created.connect(lambda _: self.show_plots(self.plots))

    def show_plots(self, plots) -> None:
        self.plots = tuple(plots)
        while self.form.rowCount():
            self.form.removeRow(0)
        self.combos.clear()
        titles = self.hub.titles()
        for plot in self.plots:
            combo = QComboBox()
            combo.addItem(self.OWN, None)
            for title in titles:
                if title != plot.title:
                    combo.addItem(title, title)
            saved = settings().value(graph_choice_key(self.procedure, plot.key))
            chosen = (saved or None) if saved is not None else plot.into
            index = combo.findData(chosen)
            combo.setCurrentIndex(max(0, index))
            combo.currentIndexChanged.connect(
                lambda _, plot=plot, combo=combo: settings().setValue(
                    graph_choice_key(self.procedure, plot.key),
                    combo.currentData() or "",
                )
            )
            self.form.addRow(plot.title, combo)
            self.combos[plot.key] = combo

    def into(self, plot: PlotInfo) -> Optional[str]:
        combo = self.combos.get(plot.key)
        return plot.into if combo is None else combo.currentData()


class CustomMeasureWidget(MeasureWidget):
    def __init__(self, session, hub, procedure: str, open_code: OpenCode, parent=None):
        self.open_code = open_code
        self.about: Optional[ProcedureSummary] = session.procedure(procedure)
        self.stale = False  # described anew while it ran: reload at its end
        self.script_id: Optional[int] = None  # the script of its last run
        super().__init__(session, hub, procedure, parent)
        self.session = session
        self.output = ScriptOutput(
            lambda file, line: open_code(procedure, line),
            "What its script prints when it runs",
        )
        self.output.setMaximumHeight(160)
        self.output_box = Collapsible("Output", f"custom/{procedure}/output")
        self.output_box.addWidget(self.output)
        self.graphs = GraphChoice(procedure, hub)
        self.graphs_box = Collapsible("Graphs", f"custom/{procedure}/graphs")
        self.graphs_box.addWidget(self.graphs)
        self.layout().addWidget(self.graphs_box)
        self.layout().addWidget(self.output_box)
        self.box.into = self.graphs.into
        scripts = session.scripts
        scripts.runs_changed.connect(self._bind)
        scripts.printed.connect(self._printed)
        scripts.output_reset.connect(self._reset)
        self.box.runner.started.connect(self._run_started)
        self.box.runner.running_changed.connect(self._running)
        session.procedures_changed.connect(self._described)
        self.show_about()
        self.show_graphs()

    def show_graphs(self) -> None:
        self.graphs.show_plots(self.box.info.plots)
        self.graphs_box.setVisible(bool(self.box.info.plots))

    def make_header(self, about) -> QWidget:
        header = QWidget()
        column = QVBoxLayout(header)
        column.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.titleLabel = QLabel()
        self.titleLabel.setProperty("role", "title")
        row.addWidget(self.titleLabel, 1)
        code = QPushButton(theme.icon("code-braces"), "Code")
        code.setToolTip("Its script, in the editor")
        code.clicked.connect(lambda: self.open_code(self.procedure_name, 0))
        row.addWidget(code)
        column.addLayout(row)
        self.aboutLabel = QLabel()
        self.aboutLabel.setWordWrap(True)
        self.aboutLabel.setProperty("role", "muted")
        column.addWidget(self.aboutLabel)
        self.errorLabel = QLabel()
        self.errorLabel.setWordWrap(True)
        self.errorLabel.setStyleSheet(f"color: {theme.BAD};")
        column.addWidget(self.errorLabel)
        return header

    def make_box(self, session, hub, procedure, header):
        self.procedure_name = procedure
        return CustomBox(session, hub, procedure, header=header)

    def show_about(self) -> None:
        about = self.about
        self.titleLabel.setText(about.title if about else self.procedure_name)
        self.aboutLabel.setText(about.description if about else "")
        self.aboutLabel.setVisible(bool(about and about.description))
        error = about.error if about else ""
        self.errorLabel.setText(f"Not described: {last_line(error)}" if error else "")
        self.errorLabel.setToolTip(error)
        self.errorLabel.setVisible(bool(error))

    # Described anew
    def _described(self) -> None:
        """The library changed: described anew (its form is not in the
        summary, and the daemon keeps descriptions by the script's hash)."""
        about = self.session.procedure(self.procedure_name)
        if about is None:
            return  # its dock goes
        self.about = about
        if self.box.runner.running:
            self.stale = True
        else:
            self._reload()

    def _reload(self) -> None:
        self.stale = False
        self.show_about()
        self.box.reload()
        self.show_graphs()

    def _running(self, running: bool) -> None:
        if not running and self.stale:
            self._reload()

    # What its script prints
    def _run_started(self, measurement) -> None:
        self.script_id = None
        self.output.clear()
        self._bind()

    def _bind(self) -> None:
        run = self.box.runner.run
        if self.script_id is not None or run is None:
            return
        found = self.session.scripts.of_measurement(run.id)
        if found is not None:
            self.script_id = found.id
            self.output.show_whole(self.session.scripts.output(found.id))
            self.output_box.set_expanded(True)

    def _printed(self, id: int, text: str) -> None:
        if id == self.script_id:
            self.output.add(text)

    def _reset(self, id: int) -> None:
        if id == self.script_id:
            self.output.show_whole(self.session.scripts.output(id))
