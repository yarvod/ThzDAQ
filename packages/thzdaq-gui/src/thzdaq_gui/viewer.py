"""The plots window: only the graphs of one measurement, without docks, a
profile or a workspace (thzdaq plot, lab.plot, run.show, m.show; ThzDAQ
--plot).

A measurement of the daemon is drawn from its snapshot, then followed by its
events; once it has ended the window stops listening, so a window left open
does not keep the daemon from going idle. A measurement file is drawn once.
A plot of one's own (its table and columns) is drawn instead of the
measurement's own.
"""

from typing import Any, Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QMainWindow, QWidget
from thzdaq_api import events, host
from thzdaq_api.devices import ListDevices
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Lab
from thzdaq_api.measurement_file import RUNNING, Column, Measurement
from thzdaq_api.measurements import (
    GetRunSnapshot,
    ListProcedures,
    PlotInfo,
    RunSnapshot,
    SummarizeMeasurement,
)
from thzdaq_api.origins import PLOTS
from thzdaq_api.windows import OwnPlot, Which, file_plots, read_file

from thzdaq_gui.bridge import Bridge
from thzdaq_gui.graphs import AddCurveDialog, GraphHub, close_plots
from thzdaq_gui.models.run import RunModel
from thzdaq_gui.run_graphs import RunGraphs

COLUMNS = 2  # graphs side by side; the next ones in further rows
PROGRAM = "ThzDAQ plots"
Call = Callable[[Any], Any]


def titled(id, title: str) -> str:
    return f"#{id} {title}"


def outcome(status: str, error: Optional[str]) -> str:
    return f"{status}: {error}" if error else status


class PlotWindow(QMainWindow):
    """The graphs of its hub in a grid, in the order they are built, and how
    their measurement stands in the title and the status bar."""

    closing = Signal()

    def __init__(self, call: Call, parent=None):
        """call: the lab's, for what graphs ask (an analysis)."""
        super().__init__(parent)
        self.hub = GraphHub((), call, self)
        self.hub.graph_created.connect(self.place)
        body = QWidget()
        self.grid = QGridLayout(body)
        self.setCentralWidget(body)
        self.state = QLabel()
        self.statusBar().addWidget(self.state, 1)
        self.resize(1100, 720)

    def place(self, graph: QWidget) -> None:
        count = self.grid.count()
        self.grid.addWidget(graph, count // COLUMNS, count % COLUMNS)

    def offer(self, measurement: Callable[[], Measurement]) -> None:
        """Add curve on a graph offers the columns of the measurement shown."""
        self.hub.add_curve_request = lambda graph: AddCurveDialog(
            [measurement()], graph, self
        ).exec()

    def tell(self, title: str, state: str) -> None:
        self.setWindowTitle(f"{title} · {PROGRAM}")
        self.state.setText(state)

    def closeEvent(self, event) -> None:
        self.closing.emit()
        close_plots()
        super().closeEvent(event)


class Following(QObject):
    """A measurement of the daemon in the window: its snapshot, then its
    events until it ends."""

    def __init__(
        self, lab: Lab, run_id: int, window: PlotWindow, own: Optional[OwnPlot] = None
    ):
        """LabError NOT_FOUND when the daemon has no measurement run_id."""
        super().__init__(window)
        self.lab, self.id, self.window = lab, run_id, window
        snapshot = lab.call(GetRunSnapshot(id=run_id))
        titles = {device.ref: device.title for device in lab.call(ListDevices())}
        self.model = RunModel(None, lambda ref: titles.get(ref, ref), self)
        chosen = () if own is None else (own.plot(self.columns(own.table)),)
        RunGraphs(window.hub, chosen, self).follow(self.model)
        self.bridge = Bridge(self)
        self.bridge.measurement_event.connect(self.hear)
        self.bridge.resync.connect(self.catch_up)
        self.model.progress.connect(self.progressed)
        self.model.finished.connect(self.ended)
        window.offer(lambda: self.model.measurement)
        window.closing.connect(self.bridge.stop)
        self.start(snapshot)

    def columns(self, table: str) -> Dict[str, Column]:
        """The columns of a table as the daemon describes them so far."""
        summary = self.lab.call(SummarizeMeasurement(id=self.id))
        return {
            c.key: Column(c.key, c.title, c.unit)
            for found in summary.tables
            if found.name == table
            for c in found.columns
        }

    def start(self, snapshot: RunSnapshot) -> None:
        """Drawn as the snapshot holds it, then followed while it runs."""
        self.model.restore(snapshot)
        if self.model.running:
            self.bridge.listen(self.lab, snapshot.seq)

    def hear(self, event: events.Event) -> None:
        if events.run_id(event.body) == self.id:
            self.model.hear(event)

    def catch_up(self, *_) -> None:
        """Events were lost (the daemon restarted): the run as it is now, or
        interrupted when the daemon no longer has it."""
        try:
            snapshot = self.lab.call(GetRunSnapshot(id=self.id))
        except LabError as e:
            if e.code != ErrorCode.NOT_FOUND:
                raise
            self.model.lost()
            return
        self.start(snapshot)

    def title(self) -> str:
        return titled(self.id, self.model.run.title)

    def progressed(self, done: int, total: Optional[int]) -> None:
        steps = f"{done}/{total}" if total else f"{done}"
        self.window.tell(self.title(), f"{RUNNING} {steps}")

    def ended(self, measurement: Measurement) -> None:
        self.bridge.stop()
        self.window.tell(self.title(), outcome(measurement.status, measurement.error))


def draw_file(
    window: PlotWindow, measurement: Measurement, plots: Tuple[PlotInfo, ...]
) -> None:
    """A saved measurement, drawn once."""
    window.offer(lambda: measurement)
    window.hub.register_plots(plots)
    window.hub.show_measurement(measurement, plots)
    window.tell(
        titled(measurement.id, measurement.title or measurement.procedure),
        outcome(measurement.status, measurement.error),
    )


def unreachable(error: LabError) -> Call:
    """The call of a lab that is not there: each tells why."""

    def call(operation):
        raise error

    return call


def open_window(
    which: Which, simulate: bool = False, own: Optional[OwnPlot] = None
) -> PlotWindow:
    """The plots window of a measurement: one of the daemon by its number,
    followed as it runs, or a file (the daemon, when one runs, knows the
    plots of its procedure). LabError when there is nothing to show."""
    if isinstance(which, int):
        lab = host.connect(simulate, PLOTS, PLOTS)  # a window starts no daemon
        window = PlotWindow(lab.call)
        Following(lab, which, window, own)
        return window
    measurement = read_file(which)
    try:
        lab = host.connect(simulate, PLOTS, PLOTS)
        call, procedures = lab.call, lab.call(ListProcedures())
    except LabError as e:
        call, procedures = unreachable(e), ()
    plots = file_plots(measurement, procedures, own)
    window = PlotWindow(call)
    draw_file(window, measurement, plots)
    return window
