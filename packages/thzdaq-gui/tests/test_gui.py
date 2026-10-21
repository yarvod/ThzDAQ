import os
import threading

import pytest
from thzdaq_core.data import CANCELLED, COMPLETED, Dataset
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.parameters import Sweep
from thzdaq_core.measurements.procedures import (
    IFNoise,
    IVCurve,
    SidebandRatio,
    SisReflection,
    TwoSbOptimization,
)
from thzdaq_gui.forms import ParameterForm, RoleMappingForm
from thzdaq_gui.plots import LinePlot, MapPlot, PlotPanel
from thzdaq_gui.workers import DeviceWorker, QtRunner
from thzdaq_instruments.capabilities import Switchable

FAST_IV = {"voltage": Sweep(0, 5e-3, 6), "settle_time": 0.0, "first_point_delay": 0.0}


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
        assert "spectrum" in procedure.roles()

    def test_multi_choice_and_errors(self, app):
        form = ParameterForm()
        form.set_procedure(SisReflection)
        form.set_values({"s_parameters": ("S21", "S12")})
        assert form.values()["s_parameters"] == ("S21", "S12")
        form.set_values({"s_parameters": ()})
        with pytest.raises(ProcedureError, match="S-parameters"):
            form.values()

    def test_role_mapping_defaults_to_same_name(self, app):
        roles = RoleMappingForm()
        roles.set_roles(
            {"bias": Switchable, "detector": Switchable}, ["sis1", "detector"]
        )
        assert roles.mapping() == {"detector": "detector"}
        assert roles.unmapped() == ["bias"]
        roles.combos["bias"].setCurrentText("sis1")
        roles.set_roles({"bias": Switchable}, ["sis1", "detector"])  # keeps the choice
        assert roles.mapping() == {"bias": "sis1"}


class TestWorkers:
    def test_device_worker_delivers_in_gui_thread(self, app, wait):
        worker = DeviceWorker()
        results, errors = [], []
        worker.submit(lambda: threading.current_thread().name, results.append)
        worker.submit(lambda: 1 / 0, None, errors.append)
        wait(lambda: results and errors)
        assert results == ["DeviceWorker"] and isinstance(errors[0], ZeroDivisionError)
        assert threading.current_thread() is threading.main_thread()
        worker.stop()

    def test_unhandled_job_error_is_signalled(self, app, wait):
        worker = DeviceWorker()
        messages = []
        worker.error.connect(messages.append)
        worker.submit(lambda: 1 / 0)
        wait(lambda: messages)
        assert "ZeroDivisionError" in messages[0]
        worker.stop()

    def test_qt_runner_streams_records(self, session, wait):
        runner = QtRunner()
        records, finished = [], []
        runner.record.connect(lambda stream, record: records.append(stream))
        runner.finished.connect(finished.append)
        runner.start(
            session.station, session.store, IVCurve(**FAST_IV), {"bias": "sis1"}
        )
        wait(lambda: finished)
        assert finished[0].status == COMPLETED and records == ["iv"] * 6
        assert os.path.exists(finished[0].metadata["path"])

    def test_qt_runner_reports_missing_roles(self, session, wait):
        runner = QtRunner()
        failures = []
        runner.failed.connect(failures.append)
        runner.start(session.station, None, IVCurve(**FAST_IV))
        wait(lambda: failures)
        assert "'bias' is not configured" in failures[0]

    def test_qt_runner_cancel(self, session, wait):
        runner = QtRunner()
        finished = []
        runner.finished.connect(finished.append)
        slow = IVCurve(
            voltage=Sweep(0, 5e-3, 1000), settle_time=0.05, first_point_delay=0
        )
        runner.start(session.station, None, slow, {"bias": "sis1"})
        wait(lambda: runner.running)
        runner.cancel()
        wait(lambda: finished)
        assert finished[0].status == CANCELLED


class TestPlots:
    def test_line_plot_groups_curves(self, app):
        panel = PlotPanel()
        panel.set_specs(IFNoise.plots)
        for load, power in (("cold", -32.0), ("hot", -30.0)):
            for f in (4e9, 5e9):
                panel.add_record(
                    "power", {"frequency": f, "load": load, "power": power}
                )
        panel.add_record(
            "noise",
            {"frequency": 4e9, "y_factor": 2.0, "noise_temperature": float("nan")},
        )
        power_plot = panel.plots[0]
        assert isinstance(power_plot, LinePlot) and len(power_plot.curves) == 2
        xs, ys = power_plot.curves[("hot",)].getData()
        assert list(xs) == [4.0, 5.0] and list(ys) == [-30.0, -30.0]
        assert panel.plots[2].curves == {}  # NaN Tn is not drawn

    def test_map_plot_grid(self, app):
        panel = PlotPanel()
        panel.set_specs(TwoSbOptimization.plots)
        for v1, v2, tn in (
            (2.1e-3, 2.1e-3, 40.0),
            (2.1e-3, 2.2e-3, 50.0),
            (2.2e-3, 2.1e-3, 60.0),
        ):
            panel.add_record(
                "map", {"sis1_voltage_set": v1, "sis2_voltage_set": v2, "tn_upper": tn}
            )
        map_plot = panel.plots[0]
        assert isinstance(map_plot, MapPlot)
        xs, ys, data = map_plot.grid()
        assert xs == pytest.approx([2.1, 2.2]) and data[0, 1] == 50.0
        assert data[1, 1] != data[1, 1]  # not measured yet: NaN

    def test_show_dataset(self, app):
        dataset = Dataset("sis.iv_curve")
        for v in (1e-3, 2e-3):
            dataset.append("iv", {"voltage": v, "current": v / 20})
        panel = PlotPanel()
        panel.show_dataset(dataset, IVCurve.plots)
        assert panel.count() == 1
        assert len(panel.plots[0].curves[()].getData()[0]) == 2


class TestMainWindow:
    def test_full_flow(self, session, wait, tmp_path):
        from thzdaq_gui.main_window import MainWindow

        window = MainWindow(session, restore_layout=False)
        window.show()
        panel = window.measurePanel
        panel.procedureCombo.setCurrentIndex(
            panel.procedureCombo.findData("sis.iv_curve")
        )
        panel.form.set_values(FAST_IV)
        panel.roles.combos["bias"].setCurrentText("sis1")
        panel.comment.setText("smoke test")
        panel.btnStart.click()
        wait(lambda: not session.runner.running and panel.btnStart.isEnabled())

        assert window.plots.count() == 1
        assert len(window.plots.plots[0].curves[()].getData()[0]) == 6
        assert window.dataPanel.table.rowCount() == 1
        assert window.dataPanel.table.item(0, 2).text() == COMPLETED
        assert window.dataPanel.table.item(0, 4).text() == "smoke test"

        opened = []
        window.dataPanel.dataset_opened.connect(opened.append)
        window.dataPanel.open_row(0)
        assert opened[0].procedure == "sis.iv_curve"

        control = window.controlPanel
        control.roleCombo.setCurrentText("lo")
        control.btnOpen.click()
        wait(lambda: control.control is not None)
        titles = [section.title() for section in control.control.sections]
        assert titles == ["Output", "Frequency", "Power"]
        frequency = control.control.sections[1]
        frequency.spin.setValue(223.0)
        frequency.writers[1].click()  # Set
        generator = session.station.instrument("lo_generator")
        wait(lambda: abs(generator.get_frequency() - 223e9 / 18) < 1)

        station_panel = window.stationPanel
        station_panel.btnCheck.click()
        wait(
            lambda: all(
                item.text(2) not in ("", "…")
                for item in station_panel.role_items.values()
            )
        )
        assert "SidebandSwitch" in station_panel.role_items["if_selector"].text(2)

        screenshot = os.environ.get("THZDAQ_GUI_SCREENSHOT")
        if screenshot:
            window.grab().save(screenshot)
        window.close()
