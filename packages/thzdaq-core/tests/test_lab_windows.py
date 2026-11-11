"""Windows a script or a command opens apart from itself (thzdaq_api.windows):
the plots window of a measurement and the main window (contract: LocalLab and
RemoteLab). The windows are programs of their own: the tests see the command
lines that would start them."""

from pathlib import Path

import pytest
from lab_helpers import Window
from thzdaq_api import host
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Bench
from thzdaq_api.measurement_file import (
    Measurement,
    read_measurement,
    write_measurement,
)
from thzdaq_api.measurements import ListProcedures, saved_plots
from thzdaq_api.origins import GUI, PLOTS
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_api.windows import OwnPlot, open_plots, which

WINDOW = "ThzDAQ"  # the window program, as the tests start it


@pytest.fixture
def started_windows(monkeypatch):
    """The command lines of the windows started, instead of starting them."""
    started = []
    monkeypatch.setattr(host, "window_command", lambda: [WINDOW])
    monkeypatch.setattr(host, "start_apart", started.append)
    return started


@pytest.fixture
def showing(lab, tmp_path):
    return Bench(lab, tmp_path, simulate=True)


def quick_iv(showing):
    return showing.run(
        CURRENT_VS_VOLTAGE, bias=showing["sis_bias_1"], voltage="0:1:3",
        settle_time=0.0, first_point_delay=0.0,
    )  # fmt: skip


def test_a_measurement_of_the_daemon_opens_in_a_plots_window(showing, started_windows):
    run = quick_iv(showing)
    run.show()
    showing.plot(run.id, table="iv", x="voltage", y="current", group_by=["load"])
    assert started_windows == [
        [WINDOW, "--plot", str(run.id), "--simulate"],
        [WINDOW, "--plot", str(run.id), "--table", "iv", "--x", "voltage",
         "--y", "current", "--group", "load", "--simulate"],
    ]  # fmt: skip


def test_a_measurement_the_daemon_does_not_know_opens_nothing(showing, started_windows):
    with pytest.raises(LabError) as caught:
        showing.plot(999)
    assert caught.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(LabError) as caught:
        showing.plot(quick_iv(showing).id, table="iv", x="voltage")
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    assert not started_windows


def test_a_file_opens_when_it_has_a_plot_to_draw(
    showing, lab, started_windows, tmp_path
):
    run = quick_iv(showing)
    path = run.wait(progress=False).path
    showing.plot(path)
    assert started_windows == [
        [WINDOW, "--plot", str(Path(path).resolve()), "--simulate"]
    ]
    # A file of a procedure the showing does not know has none of its own
    unknown = Measurement("elsewhere.sweep", "Sweep", 1)
    unknown.append("t", {"x": 1.0, "y": 2.0})
    other = write_measurement(unknown, tmp_path / "other.json")
    with pytest.raises(LabError) as caught:
        showing.plot(other)
    assert caught.value.code == ErrorCode.NOT_FOUND
    showing.plot(other, table="t", x="x", y="y")
    with pytest.raises(LabError) as caught:
        showing.plot(tmp_path / "missing.json")
    assert caught.value.code == ErrorCode.NOT_FOUND
    assert len(started_windows) == 2


def test_a_saved_measurement_draws_its_procedures_plots_and_its_own(showing, lab):
    procedures = lab.call(ListProcedures())
    path = quick_iv(showing).wait(progress=False).path
    plots = saved_plots(read_measurement(path), procedures)
    assert [p.table for p in plots] == ["iv"]
    # The file keeps them: it is drawn so without the catalog
    assert saved_plots(read_measurement(path), ()) == plots
    with showing.measurement("pv") as m:
        drawn = m.plot("scan", x="voltage", y="power")
        m.record("scan", voltage=1e-3, power=-30.0)
    plots = saved_plots(read_measurement(m.run.path), procedures)
    assert plots == (drawn,)


def test_a_scripts_measurement_is_shown_once_where_asked(showing, started_windows):
    with showing.measurement("pv") as m:
        m.plot("scan", x="voltage", y="power", show=True)
        m.plot("y", x="voltage", y="y_factor", show=PLOTS)
        m.show()
        assert started_windows == [[WINDOW, "--plot", str(m.id), "--simulate"]]
        m.show(GUI)  # no main window listens: one opens in the workspace
        m.show(GUI)
    assert started_windows[1:] == [
        [WINDOW, "--workspace", str(showing.workspace), "--simulate"]
    ]
    with pytest.raises(LabError) as caught:
        showing.show(m.id, "terminal")
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS


def test_a_main_window_open_shows_the_measurement_already(
    showing, lab_as, started_windows
):
    window = Window(lab_as(GUI))
    try:
        with showing.measurement("pv") as m:
            m.plot("scan", x="voltage", y="power", show=GUI)
    finally:
        window.stop()
    assert not started_windows


def test_an_own_plot_is_named_by_its_columns():
    assert OwnPlot.asked() is None
    own = OwnPlot.asked("pv", "voltage", "power", ["angle"])
    assert own.arguments() == [
        "--table", "pv", "--x", "voltage", "--y", "power", "--group", "angle"
    ]  # fmt: skip
    plot = own.plot({})
    assert (plot.table, plot.x, plot.y, plot.group_by) == (
        "pv", "voltage", "power", ("angle",)
    )  # fmt: skip
    assert plot.x_label == "Voltage, V" and plot.y_label.startswith("Power")
    with pytest.raises(LabError):
        OwnPlot.asked(group_by=["angle"])
    assert which("57") == 57 and which("data/57_x.json") == "data/57_x.json"


def test_a_command_line_opens_through_the_same_check(lab, started_windows):
    with pytest.raises(LabError):
        open_plots(lab.call, 12345)
    assert not started_windows
