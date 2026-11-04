"""The plots window (thzdaq plot): only the graphs of one measurement, drawn
from the daemon's snapshot and then by its events, or from a file."""

import pytest
from thzdaq_api import host
from thzdaq_api.daemon import GetDaemonStatus
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import COMPLETED, INTERRUPTED, RUNNING
from thzdaq_api.measurements import (
    GetRunSnapshot,
    PlotInfo,
    StartMeasurement,
    WaitMeasurement,
)
from thzdaq_api.origins import CLI, PLOTS
from thzdaq_api.procedures import IV_CURVE
from thzdaq_api.sessions import EndSession, PlotSession, RecordSession, StartSession
from thzdaq_api.windows import OwnPlot

FAST_IV = {
    "voltage": {"start": 0, "stop": 0.002, "points": 6},
    "settle_time": 0.0,
    "first_point_delay": 0.0,
}


@pytest.fixture
def assembled(connect):
    return connect(True).assembled


@pytest.fixture
def lab_as(assembled):
    """The bench as a client calls it: the plots window, the command line."""
    from thzdaq_core.application.local import LocalLab

    return lambda origin: LocalLab(assembled, origin, origin)


@pytest.fixture
def cli(lab_as):
    return lab_as(CLI)


@pytest.fixture
def windows():
    """Plots windows of a test, closed after it."""
    opened = []
    yield opened
    for window in opened:
        window.close()


@pytest.fixture
def follow(lab_as, windows):
    from thzdaq_gui.viewer import Following, PlotWindow

    def opened(run_id, own=None):
        lab = lab_as(PLOTS)
        window = PlotWindow(lab.call)
        windows.append(window)
        return window, Following(lab, run_id, window, own)

    return opened


def points(graph) -> int:
    return sum(len(curve) for curve in graph.points.values())


def scan(cli, *voltages):
    """A script's session with a plot of its scan, records so far."""
    run = cli.call(StartSession(title="pv_fine"))
    asked = PlotInfo(key="", title="", table="scan", x="voltage", y="power")
    plot = cli.call(PlotSession(id=run.id, plot=asked))
    record(cli, run.id, *voltages)
    return run, plot


def record(cli, run_id, *voltages):
    for v in voltages:
        row = {"voltage": v, "power": -30.0, "load": "hot"}
        cli.call(RecordSession(id=run_id, table="scan", rows=(row,)))


def listening(lab) -> bool:
    clients = lab.call(GetDaemonStatus()).clients
    return any(client.kind == PLOTS for client in clients)


def test_the_window_gets_points_by_events_until_the_run_ends(cli, follow, wait):
    run, plot = scan(cli, 1e-3, 2e-3)
    window, following = follow(run.id)
    graph = window.hub.graphs[plot.title]
    assert points(graph) == 2  # from the snapshot
    assert window.grid.itemAt(0).widget() is graph
    assert window.windowTitle().startswith(f"#{run.id} pv_fine")
    assert listening(cli)
    record(cli, run.id, 3e-3, 4e-3)
    wait(lambda: points(graph) == 4)  # by events
    assert window.state.text().startswith(RUNNING)
    # A plot the script adds while it runs comes next to the first
    asked = PlotInfo(key="", title="", table="scan", x="voltage", y="load")
    added = cli.call(PlotSession(id=run.id, plot=asked))
    wait(lambda: added.title in window.hub.graphs)
    assert window.grid.count() == 2
    cli.call(EndSession(id=run.id))
    wait(lambda: window.state.text() == COMPLETED)
    # Ended: the window stops listening and does not keep the daemon up
    assert not listening(cli)
    assert points(graph) == 4


def test_an_ended_run_is_drawn_whole_without_listening(cli, follow, wait):
    run = cli.call(
        StartMeasurement(
            procedure=IV_CURVE, parameters=FAST_IV, devices={"bias": "sis_bias_1"}
        )
    )
    assert cli.call(WaitMeasurement(id=run.id, timeout=10)).status == COMPLETED
    window, _ = follow(run.id)
    graph = window.hub.graphs["I-V"]
    assert points(graph) == 6
    assert window.state.text() == COMPLETED and not listening(cli)


def test_a_plot_of_ones_own_is_drawn_instead(cli, follow, wait):
    run, plot = scan(cli, 1e-3)
    own = OwnPlot.asked("scan", "voltage", "power", ["load"])
    window, _ = follow(run.id, own)
    assert list(window.hub.graphs) == ["Power – Voltage"]
    graph = window.hub.graphs["Power – Voltage"]
    assert graph.x.label == "Voltage, V" and [k[-1] for k in graph.points] == [("hot",)]
    asked = PlotInfo(key="", title="", table="scan", x="voltage", y="load")
    cli.call(PlotSession(id=run.id, plot=asked))
    record(cli, run.id, 2e-3)
    wait(lambda: points(graph) == 2)
    assert list(window.hub.graphs) == ["Power – Voltage"]  # only the one asked for
    cli.call(EndSession(id=run.id))


def test_a_run_the_restarted_daemon_lost_ends_interrupted(cli, follow, wait):
    run, _ = scan(cli, 1e-3)
    window, following = follow(run.id)

    class Restarted:
        """The new daemon: it never had the run."""

        origin = PLOTS

        def call(self, operation):
            if isinstance(operation, GetRunSnapshot):
                raise LabError(ErrorCode.NOT_FOUND, "No measurement")
            return cli.call(operation)

        def subscribe(self, listener, since=None):
            return lambda: None

    following.lab = Restarted()
    following.catch_up()
    assert window.state.text() == INTERRUPTED
    cli.call(EndSession(id=run.id))


def test_an_unknown_measurement_opens_no_window(lab_as, follow):
    with pytest.raises(LabError) as caught:
        follow(999)
    assert caught.value.code == ErrorCode.NOT_FOUND


def test_a_file_is_drawn_once_with_the_plots_it_was_made_with(
    cli, lab_as, windows, monkeypatch
):
    from thzdaq_gui.viewer import open_window

    run, plot = scan(cli, 1e-3, 2e-3)
    path = cli.call(EndSession(id=run.id)).path
    iv = cli.call(
        StartMeasurement(
            procedure=IV_CURVE, parameters=FAST_IV, devices={"bias": "sis_bias_1"}
        )
    )
    iv_path = cli.call(WaitMeasurement(id=iv.id, timeout=10)).path
    monkeypatch.setattr(host, "connect", lambda *_: lab_as(PLOTS))
    window = open_window(iv_path)
    windows.append(window)
    assert points(window.hub.graphs["I-V"]) == 6  # a plot of its procedure
    assert window.state.text() == COMPLETED and not listening(cli)

    def no_daemon(*_):
        raise LabError(ErrorCode.UNREACHABLE, "No daemon runs")

    monkeypatch.setattr(host, "connect", no_daemon)
    window = open_window(path)  # its own plots are in the file
    windows.append(window)
    assert points(window.hub.graphs[plot.title]) == 2
    with pytest.raises(LabError):
        open_window(iv_path)  # the plots of a procedure come from the daemon
    window = open_window(iv_path, own=OwnPlot.asked("iv", "voltage", "current"))
    windows.append(window)
    assert points(window.hub.graphs["Current – Voltage"]) == 6
    with pytest.raises(LabError) as caught:
        open_window(iv_path, own=OwnPlot.asked("pv", "voltage", "power"))
    assert "'pv'" in caught.value.message


def test_the_program_with_plot_is_only_the_plots_window(cli, lab_as, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from thzdaq_gui.app import main

    run, _ = scan(cli, 1e-3)
    monkeypatch.setattr(host, "connect", lambda *_: lab_as(PLOTS))
    assert main(["--plot", str(run.id), "--quit-after", "0"]) == 0
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: told.append(a[2]))
    assert main(["--plot", "999", "--quit-after", "0"]) == 1
    assert told and "999" in told[0]
    cli.call(EndSession(id=run.id))
