"""Measurements started by another client belong in the same GUI views."""

import pytest

from thzdaq_api.devices import ReadDevice, SetQuantity
from thzdaq_api.events import Resync
from thzdaq_api.measurement_file import CANCELLED, COMPLETED, read_measurement
from thzdaq_api.measurements import (
    CancelMeasurement,
    GetRunSnapshot,
    StartMeasurement,
    WaitMeasurement,
)
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE, MONITOR_VALUES_VS_TIME


@pytest.fixture
def cli(session):
    lab = session.lab_of(True)
    lab.origin = "cli"
    return lab


def monitor(lab):
    return lab.call(
        StartMeasurement(
            procedure=MONITOR_VALUES_VS_TIME,
            parameters={"watch": ["power_meter_1/power"], "interval": 0.02},
        )
    )


def test_cli_measurement_reaches_data_graphs_and_processes(window, session, cli, wait):
    processes = []
    session.processes.added.connect(
        lambda process: processes.append(
            (process.title, process in window.processesWidget.rows)
        )
    )
    run = cli.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            parameters={
                "voltage": {"start": 0, "stop": 0.002, "points": 6},
                "settle_time": 0.05,
                "first_point_delay": 0,
            },
            devices={"bias": "sis_bias_1"},
        )
    )
    wait(lambda: session.measurements.items)
    measurement = session.measurements.items[0]
    assert measurement.id == run.id
    assert len(processes) == 1 and processes[0][1]
    assert "cli" in processes[0][0]
    wait(lambda: measurement.status == COMPLETED)
    assert measurement.size == 6
    assert len(session.measurements.items) == 1
    assert not session.processes.items
    graph = window.hub.graph("I-V")
    assert sum(len(points) for points in graph.points.values()) == 6


def test_a_scripts_plot_added_while_it_runs_is_drawn(window, session, cli, wait):
    from thzdaq_api.measurements import PlotInfo
    from thzdaq_api.sessions import EndSession, PlotSession, RecordSession
    from thzdaq_api.sessions import StartSession

    run = cli.call(StartSession(title="pv_fine"))
    asked = PlotInfo(key="", title="", table="scan", x="voltage", y="power")
    plot = cli.call(PlotSession(id=run.id, plot=asked))
    for v in (1e-3, 2e-3):
        row = {"voltage": v, "power": -30.0}
        cli.call(RecordSession(id=run.id, table="scan", rows=(row,)))
    wait(lambda: plot.title in window.hub.graphs)
    graph = window.hub.graph(plot.title)
    wait(lambda: sum(len(points) for points in graph.points.values()) == 2)
    cli.call(EndSession(id=run.id))


def test_a_scripts_measurement_is_stopped_from_processes_and_restored(
    window, session, cli, wait
):
    """The grid's hot/cold P-V (thzdaq_api/examples/hot_cold_grid.py) as
    its script drives it: seen in Processes and its graph, Stop there
    cancels it, the daemon sets the bias and the grid back."""
    from thzdaq_api.devices import CallAction
    from thzdaq_api.measurements import PlotInfo
    from thzdaq_api.sessions import (
        CallOnExit,
        EndSession,
        KeepSession,
        RecordSession,
        RestoreOnExit,
        StartSession,
    )

    bias, grid, load = "sis_bias_1", "grid_1", "chopper_1"
    cli.call(SetQuantity(ref=bias, key="voltage_set", value="1mV"))
    cli.call(SetQuantity(ref=grid, key="angle", value="15"))
    pv = PlotInfo(
        key="p_v", title="P-V", table="pv", x="voltage", y="power",
        group_by=("angle", "load"),
    )  # fmt: skip
    run = cli.call(
        StartSession(
            title="pv_hot_cold_grid", devices=(bias, grid, load),
            exclusive=(bias, grid), plots=(pv,),
        )  # fmt: skip
    )
    cli.call(RestoreOnExit(id=run.id, ref=bias, key="voltage_set"))
    cli.call(RestoreOnExit(id=run.id, ref=grid, key="angle"))
    cli.call(CallOnExit(id=run.id, ref=load, action="to_cold"))
    cli.call(SetQuantity(ref=grid, key="angle", value="40", session=run.id))
    cli.call(CallAction(ref=load, action="to_hot", session=run.id))
    cli.call(SetQuantity(ref=bias, key="voltage_set", value="2mV", session=run.id))
    row = {"angle": 40.0, "load": "hot", "voltage": 2e-3, "power": -30.0}
    cli.call(RecordSession(id=run.id, table="pv", rows=(row,)))

    wait(lambda: session.processes.items)
    (process,) = session.processes.items
    assert f"#{run.id}" in process.title
    wait(lambda: pv.title in window.hub.graphs)
    process.stop()
    assert cli.call(KeepSession(id=run.id, wait=5)).cancelled  # the script hears it
    cli.call(EndSession(id=run.id, status=CANCELLED))
    wait(lambda: not session.processes.items)
    assert session.measurements.items[0].status == CANCELLED

    def now(ref, key):
        return cli.call(ReadDevice(ref=ref, keys=(key,))).values[key]

    assert now(bias, "voltage_set") == pytest.approx(1e-3)
    assert now(grid, "angle") == pytest.approx(15.0)
    assert now(load, "load_state") == "cold"


def test_process_stop_cancels_an_external_monitor(window, session, cli, wait):
    run = monitor(cli)
    wait(lambda: session.processes.items)
    process = session.processes.items[0]
    assert "cli" in process.title and f"#{run.id}" in process.title
    process.stop()
    wait(lambda: not session.processes.items)
    assert session.measurements.items[0].status == CANCELLED
    assert cli.call(WaitMeasurement(id=run.id, timeout=0)).status == CANCELLED


def test_connect_catches_up_with_records_before_the_window_exists(
    session, cli, wait, tmp_path, request
):
    from thzdaq_gui.main_window import MainWindow

    session.bridge.stop()
    run = monitor(cli)
    wait(lambda: cli.call(GetRunSnapshot(id=run.id)).run.done >= 3)
    session.open(True)
    measurement = session.measurements.items[0]
    assert measurement.size >= 3
    window = MainWindow(
        session, str(tmp_path / "late.ini"), restore_layout=False, check_updates=False
    )
    request.addfinalizer(window.close)
    window.show()
    assert len(window.processesWidget.rows) == 1
    session.processes.items[0].stop()
    wait(lambda: measurement.status == CANCELLED)
    assert len(session.measurements.items) == 1
    assert measurement.size == read_measurement(measurement.metadata["path"]).size
    graph = window.hub.graph("P-t")
    assert sum(len(points) for points in graph.points.values()) == measurement.size


def test_resync_restores_missed_rows_and_finish_without_duplicates(
    window, session, cli, wait
):
    run = monitor(cli)
    wait(lambda: session.measurements.items and session.measurements.items[0].size)
    measurement = session.measurements.items[0]
    session.bridge.stop()
    cli.call(CancelMeasurement(id=run.id))
    assert cli.call(WaitMeasurement(id=run.id)).status == CANCELLED
    session.bridge.resync.emit(Resync())
    assert measurement.status == CANCELLED
    assert not session.processes.items
    assert len(session.measurements.items) == 1
    assert measurement.size == read_measurement(measurement.metadata["path"]).size
    graph = window.hub.graph("P-t")
    assert sum(len(points) for points in graph.points.values()) == measurement.size


def test_another_gui_is_also_an_external_client(window, session, cli, wait):
    cli.origin = "gui"
    run = monitor(cli)
    wait(lambda: session.measurements.items)
    assert session.measurements.items[0].id == run.id
    assert len(session.processes.items) == 1
    session.processes.items[0].stop()
    wait(lambda: not session.processes.items)


def test_reopening_the_same_lab_keeps_one_measurement(window, session, cli, wait):
    run = monitor(cli)
    wait(lambda: session.measurements.items and session.measurements.items[0].size)
    measurement = session.measurements.items[0]
    session.open(True)
    assert session.measurements.items == [measurement]
    assert len(session.processes.items) == 1
    session.processes.items[0].stop()
    wait(lambda: measurement.status == CANCELLED)
    assert measurement.size == cli.call(GetRunSnapshot(id=run.id)).run.done


def test_resync_removes_a_run_absent_from_the_daemon(
    window, session, cli, wait, monkeypatch
):
    from thzdaq_api.measurement_file import INTERRUPTED
    from thzdaq_api.measurements import ListRuns

    run = monitor(cli)
    wait(lambda: session.measurements.items and session.measurements.items[0].size)
    measurement = session.measurements.items[0]
    session.bridge.stop()
    cli.call(CancelMeasurement(id=run.id))
    cli.call(WaitMeasurement(id=run.id))
    call = session.lab.call
    monkeypatch.setattr(
        session.lab, "call", lambda op: () if isinstance(op, ListRuns) else call(op)
    )
    session.bridge.resync.emit(Resync())
    assert measurement.status == INTERRUPTED
    assert not session.processes.items


def test_closing_the_window_leaves_the_external_run_in_the_daemon(
    window, session, cli, wait
):
    run = monitor(cli)
    wait(lambda: session.processes.items)
    window.close()
    assert cli.call(WaitMeasurement(id=run.id, timeout=0)).status == "running"
    cli.call(CancelMeasurement(id=run.id))


def test_local_start_events_before_the_reply_do_not_create_another_model(
    window, session, wait, monkeypatch
):
    from threading import Event

    accepted, reply = Event(), Event()
    call = session.lab.call

    def delayed(operation):
        result = call(operation)
        if isinstance(operation, StartMeasurement):
            accepted.set()
            assert reply.wait(5)
        return result

    monkeypatch.setattr(session.lab, "call", delayed)
    box = window.measures.run(CURRENT_VS_VOLTAGE)
    box.form.set_values(
        {
            "voltage": {"start": 0, "stop": 0.001, "points": 3},
            "settle_time": 0,
            "first_point_delay": 0,
        }
    )
    box.devices.combos["bias"].setCurrentIndex(
        box.devices.combos["bias"].findData("sis_bias_1")
    )
    try:
        box.start()
        wait(accepted.is_set)
        assert session.measurements.items == []
        assert len(session.processes.items) == 1
    finally:
        reply.set()
    wait(lambda: session.measurements.items and not box.runner.running)
    assert len(session.measurements.items) == 1
    assert session.measurements.items[0].size == 3
    assert not session.run_events.external
    assert sum(len(points) for points in window.hub.graph("I-V").points.values()) == 3


def test_snapshot_values_appear_in_device_docks(session, cli, window, wait):
    cli.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="2.5mV"))
    cli.call(ReadDevice(ref="sis_bias_1"))
    session.open(True)
    panel = window.docks["device:sis_bias_1"].widget().panels[0]
    assert panel.values["voltage"].text() == "2.5 mV"
    cli.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1.5mV"))
    wait(lambda: panel.fields["voltage_set"].value() == pytest.approx(0.0015))


def test_known_values_are_not_readings(session, cli, window, wait):
    """What the lab knows is shown, but ends no read and goes on no graph."""
    cli.call(ReadDevice(ref="sis_bias_1"))
    session.open(True)
    from thzdaq_gui.graphs import GraphWidget

    panel = window.docks["device:sis_bias_1"].widget().panels[0]
    panel.plot.setChecked(True)
    panel.pending = True  # a read of the panel on its way
    panel.show_observed(panel.model.known_values)
    assert panel.values["voltage"].text() != "--"
    cli.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1.5mV"))
    wait(lambda: panel.fields["voltage_set"].value() == pytest.approx(0.0015))
    assert panel.pending
    monitored = [
        key
        for graph in window.hub.graphs.values()
        if isinstance(graph, GraphWidget)
        for key in graph.points
        if key[0] == "monitor"
    ]
    assert monitored == []
