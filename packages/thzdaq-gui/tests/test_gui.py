import os
import threading

import numpy as np
import pytest
from thzdaq_core.data import CANCELLED, COMPLETED, Measurement
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.parameters import Sweep
from thzdaq_core.measurements.procedures import (
    IFNoise,
    IVCurve,
    PVCurve,
    SidebandRatio,
    SisReflection,
    TwoSbOptimization,
)
from thzdaq_gui.forms import DeviceSlotsForm, ParameterForm
from thzdaq_gui.graphs import (
    AddCurveDialog,
    Axis,
    GraphHub,
    GraphWidget,
    MapGraphWidget,
)
from thzdaq_gui.workers import DeviceWorker, QtRunner
from thzdaq_instruments.capabilities import (
    PowerDetector,
    VoltageCurrentMeter,
    VoltageSource,
)

FAST_IV = {"voltage": Sweep(0, 5e-3, 6), "settle_time": 0.0, "first_point_delay": 0.0}
BIAS = (VoltageSource, VoltageCurrentMeter)


class TestForms:
    def test_defaults_roundtrip_through_widgets(self, app):
        form = ParameterForm()
        form.set_procedure(SidebandRatio)
        assert SidebandRatio(**form.values()).to_json() == SidebandRatio().to_json()

    def test_edit_in_display_units(self, app):
        form = ParameterForm()
        form.set_procedure(SidebandRatio)
        form.set_values({"frequency": Sweep(4e9, 6e9, 5), "detector": "spectrum"})
        start = form.editors["frequency"].widget.layout().itemAt(0).widget()
        assert start.value() == pytest.approx(4.0) and start.suffix() == " GHz"
        procedure = form.procedure()
        assert procedure.frequency == Sweep(4e9, 6e9, 5)
        assert "spectrum" in procedure.slots()

    def test_multi_choice_and_errors(self, app):
        form = ParameterForm()
        form.set_procedure(SisReflection)
        form.set_values({"s_parameters": ("S21", "S12")})
        assert form.values()["s_parameters"] == ("S21", "S12")
        form.set_values({"s_parameters": ()})
        with pytest.raises(ProcedureError, match="S-parameters"):
            form.values()

    def test_changes_are_signalled(self, app):
        form = ParameterForm()
        form.set_procedure(PVCurve)
        changed = []
        form.changed.connect(lambda: changed.append(1))
        form.editors["hot_cold"].widget.setChecked(True)
        assert changed

    def test_device_slots_offer_only_suitable_devices(self, session):
        slots = DeviceSlotsForm()
        slots.set_slots(
            {"sis1": BIAS, "sis2": BIAS, "detector": PowerDetector},
            session.station,
            preferred={"sis2": "sis_bias_1"},
            kinds={"sis1": "sis_bias", "sis2": "sis_bias"},
        )
        combo = slots.combos["sis1"]
        assert [combo.itemData(i) for i in range(combo.count())] == [
            "sis_bias_1", "sis_bias_2",
        ]  # fmt: skip
        # A preferred device wins, the other slot takes the next free one
        assert slots.mapping() == {
            "sis1": "sis_bias_2", "sis2": "sis_bias_1", "detector": "power_meter_1",
        }  # fmt: skip
        assert combo.itemText(0) == "SIS1" and slots.unmapped() == []


class TestWorkers:
    def test_device_worker_delivers_in_gui_thread(self, app, wait):
        worker = DeviceWorker()
        results, errors = [], []
        worker.submit(lambda: threading.current_thread().name, results.append)
        worker.submit(lambda: 1 / 0, None, errors.append)
        wait(lambda: results and errors)
        assert results == ["DeviceWorker"] and isinstance(errors[0], ZeroDivisionError)
        worker.stop()

    def test_unhandled_job_error_is_signalled(self, app, wait):
        worker = DeviceWorker()
        messages = []
        worker.error.connect(messages.append)
        worker.submit(lambda: 1 / 0)
        wait(lambda: messages)
        assert "ZeroDivisionError" in messages[0]
        worker.stop()

    def test_qt_runner_streams_records_and_saves_json(self, session, wait):
        runner = QtRunner()
        records, finished = [], []
        runner.record.connect(lambda table, record: records.append(table))
        runner.finished.connect(finished.append)
        runner.start(
            session.station, session.store, IVCurve(**FAST_IV), {"bias": "sis_bias_1"}
        )
        wait(lambda: finished)
        measurement = finished[0]
        assert measurement.status == COMPLETED and records == ["iv"] * 6
        assert measurement.metadata["path"].endswith(".json")
        assert os.path.exists(measurement.metadata["path"])
        assert measurement.devices["bias"].title == "SIS1"

    def test_qt_runner_reports_a_missing_device(self, session, wait):
        runner = QtRunner()
        failures = []
        runner.failed.connect(failures.append)
        runner.start(session.station, None, IVCurve(**FAST_IV))
        wait(lambda: failures)
        assert "no device 'bias'" in failures[0]

    def test_qt_runner_cancel(self, session, wait):
        runner = QtRunner()
        finished = []
        runner.finished.connect(finished.append)
        slow = IVCurve(
            voltage=Sweep(0, 5e-3, 1000), settle_time=0.05, first_point_delay=0
        )
        runner.start(session.station, None, slow, {"bias": "sis_bias_1"})
        wait(lambda: runner.running)
        runner.cancel()
        wait(lambda: finished)
        assert finished[0].status == CANCELLED


def iv_measurement(number=1) -> Measurement:
    measurement = Measurement("sis.iv_curve", title="SIS I-V curve", id=number)
    for v in (1e-3, 2e-3, 3e-3):
        measurement.append("iv", {"voltage": v, "current": v / 20})
    return measurement


@pytest.fixture
def hub(app):
    hub = GraphHub()
    yield hub
    hub.close()
    app.processEvents()


class TestGraphs:
    def test_hub_has_a_graph_per_curve_kind(self, hub):
        titles = hub.titles()
        assert {"I-V", "P-V", "Y-V", "Tn-V", "P-IF", "P-t", "I-CL"} <= set(titles)
        assert len(titles) == len(set(titles))
        assert isinstance(hub.graph("Tn upper"), MapGraphWidget)
        assert hub.graph("I-V").analysis is not None

    def test_live_records_make_one_curve_per_run_and_group(self, hub):
        run = Measurement("if.hot_cold", title="IF noise", id=7)
        for load, power in (("cold", -32.0), ("hot", -30.0)):
            for f in (4e9, 5e9):
                record = {"frequency": f, "load": load, "power": power}
                hub.feed(run, IFNoise.plots, "power", record)
        hub.feed(
            run,
            IFNoise.plots,
            "noise",
            {"frequency": 4e9, "noise_temperature": float("nan")},
        )
        graph = hub.graph("P-IF")
        assert len(graph.items) == 2
        hot = next(k for k in graph.items if k[-1] == ("hot",))
        xs, ys = graph.items[hot].getData()
        assert list(xs) == [4.0, 5.0] and list(ys) == [-30.0, -30.0]
        assert graph.curve_label(hot) == "#7 IF noise hot"
        assert hub.graph("Tn-IF").items == {}  # NaN is not drawn

    def test_map_graph_grid(self, hub):
        run = Measurement("two_sb.optimization")
        for v1, v2, tn in (
            (2.1e-3, 2.1e-3, 40.0),
            (2.1e-3, 2.2e-3, 50.0),
            (2.2e-3, 2.1e-3, 60.0),
        ):
            record = {"sis1_voltage_set": v1, "sis2_voltage_set": v2, "tn_upper": tn}
            hub.feed(run, TwoSbOptimization.plots, "map", record)
        xs, ys, data = hub.graph("Tn upper").grid()
        assert xs == pytest.approx([2.1, 2.2]) and data[0, 1] == 50.0
        assert np.isnan(data[1, 1])

    def test_saved_measurement_and_manual_curves(self, hub):
        measurement = iv_measurement()
        assert hub.show_measurement(measurement, IVCurve.plots) == ["I-V"]
        graph = hub.graph("I-V")
        (key,) = graph.items
        assert list(graph.items[key].getData()[0]) == pytest.approx([1, 2, 3])  # mV
        custom = GraphWidget("Custom", Axis(), Axis())
        hub.graphs["Custom"] = custom  # deleted with the hub
        dialog = AddCurveDialog([measurement], custom)
        dialog.x.setCurrentIndex(dialog.x.findData("voltage"))
        dialog.y.setCurrentIndex(dialog.y.findData("current"))
        dialog.accept_choice()
        assert len(custom.items) == 1 and custom.x.unit == "V" and custom.y.unit == "A"
        custom.items[next(iter(custom.items))].setVisible(False)
        custom.remove_hidden()
        assert custom.items == {}

    def test_monitor_values(self, hub):
        from thzdaq_instruments.quantities import Quantity

        power = Quantity("power", "Power", "dBm", get=lambda t: 0)
        angle = Quantity("angle", "Angle", "deg", get=lambda t: 0)
        for t, p in ((0, -30.0), (1, -31.0)):
            assert hub.monitor_value("power_meter_1", "NRX", power, t, p) == "P-t"
        assert hub.monitor_value("x", "X", angle, 0, 1.0) == "Value-t"
        assert hub.monitor_value("x", "X", angle, 1, None) is None
        graph = hub.graph("P-t")
        assert list(graph.items) == [("monitor", "power_meter_1", "power")]
        key = ("monitor", "power_meter_1", "power")
        assert graph.curve_label(key) == "NRX Power"

    def test_plot_window_keeps_the_last_part(self, hub):
        graph = hub.graph("P-t")
        for t in range(100):
            graph.append("c", "c", t, -30.0, window=10)
        assert [x for x, _ in graph.points["c"]] == list(range(89, 100))
        for t in range(100, 103):
            graph.append("c", "c", t, -30.0)
        assert len(graph.points["c"]) == 14  # no window: nothing dropped


def test_device_worker_reports_how_long_a_job_waits(app, wait):
    import time as _time

    worker = DeviceWorker()
    assert worker.busy_for() == 0
    done = []
    worker.submit(lambda: _time.sleep(0.3), done.append)
    wait(lambda: worker.busy_for() > 0.1)
    wait(lambda: done)
    assert worker.busy_for() == 0
    worker.stop()


def test_second_instance_is_detected(app, tmp_path):
    from thzdaq_gui.app import _locks, instance_lock

    path = tmp_path / "thzdaq.lock"
    first = instance_lock(path)
    assert first is not None
    assert instance_lock(path) is None  # the lock is held
    first.unlock()
    _locks.remove(first)
    assert instance_lock(path) is not None


def test_app_icon_has_a_drawing_for_every_size(app):
    from thzdaq_gui import theme

    icon = theme.app_icon()
    sizes = sorted(size.width() for size in icon.availableSizes())
    assert sizes == list(theme.APP_ICON_SIZES)
    # Pixel art: the small sizes are drawn, not scaled down from a big picture
    pixmap = icon.pixmap(16, 16).toImage()
    assert pixmap.width() == 16 and pixmap.pixelColor(8, 0).alpha() == 255


class TestDockBody:
    def test_built_on_first_open_and_kept_while_closed(self, app):
        from PySide6.QtWidgets import QLabel
        from thzdaq_gui.docks.body import DockBody

        made = []

        def factory():
            made.append(QLabel("content"))
            return made[-1]

        body = DockBody(factory)
        assert not body.built and made == []
        body.set_open(True)
        assert body.attached and made[0].parent() is body
        body.set_open(False)
        content = made[0]
        assert content.parent() is None and not content.isVisible()
        assert body.text() == "content"  # reaches the content while detached
        body.set_open(True)
        assert len(made) == 1 and body.attached
        body.replace(factory)
        assert len(made) == 2 and body.attached and body.content() is made[1]
        body.dispose()
        assert not body.built
