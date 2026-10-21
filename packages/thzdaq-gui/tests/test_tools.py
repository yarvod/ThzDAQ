import json
import os
import shutil

import numpy as np
import pytest
from conftest import EXAMPLE
from PySide6.QtWidgets import QMessageBox
from thzdaq_core.data import COMPLETED
from thzdaq_core.measurements.procedures import IVCurve
from thzdaq_core.sis import default_sis_calibration, evaluate_sis_calibration
from thzdaq_core.station import load_station
from thzdaq_core.station.config import RoleConfig
from thzdaq_gui.plots import PlotPanel
from thzdaq_gui.profile_editor import ProfileEditor, flow


@pytest.fixture
def own_profile(tmp_path):
    path = tmp_path / "bench.yaml"
    shutil.copy(EXAMPLE, path)
    return path


@pytest.fixture
def tmp_session(app, tmp_path, own_profile):
    from thzdaq_gui.session import Session

    session = Session(str(tmp_path / "data"))
    session.load_station(own_profile, simulate=True)
    yield session
    session.shutdown()


class TestIVAnalysis:
    def test_analysis_on_a_plotted_curve(self, app, monkeypatch):
        monkeypatch.setattr(
            "thzdaq_gui.iv_analysis.load_parameters",
            lambda: __import__(
                "thzdaq_core.analysis.iv", fromlist=["IVAnalysisParameters"]
            ).IVAnalysisParameters(),
        )
        panel = PlotPanel()
        panel.set_specs(IVCurve.plots)
        plot = panel.plots[0]
        assert plot.analysis is not None
        # SIS-like curve: 500 Ohm below a 2.8 mV gap, 20 Ohm above
        for v in np.linspace(0.05e-3, 7e-3, 300):
            step = 1 / (1 + np.exp(-(v - 2.8e-3) / 0.03e-3))
            current = v / 500 + (v - 2.5e-3) / 20 * step
            panel.add_record("iv", {"voltage": v, "current": current})
        assert plot.analysis.curve.count() == 1
        result = plot.analysis.analyze()
        assert result.rn_ohm == pytest.approx(1 / (1 / 20 + 1 / 500), rel=0.02)
        assert result.rj_ohm > 100
        assert result.gap is not None and result.vgap_mv == pytest.approx(2.8, abs=0.1)
        assert len(plot.analysis.overlay.items) >= 4
        assert "Rn" in plot.analysis.label.text()
        plot.analysis.clear()
        assert plot.analysis.overlay.items == []

    def test_analysis_needs_a_curve(self, app):
        panel = PlotPanel()
        panel.set_specs(IVCurve.plots)
        assert panel.plots[0].analysis.analyze() is None

    def test_parameters_dialog_validates(self, app):
        from thzdaq_core.analysis.iv import IVAnalysisParameters
        from thzdaq_gui.iv_analysis import ParametersDialog

        dialog = ParametersDialog(IVAnalysisParameters())
        dialog.rn_min.setValue(3.5)
        assert dialog.build().resistance.rn_min_voltage_mv == 3.5
        dialog.window.setValue(4)  # even window is invalid
        with pytest.raises(ValueError):
            dialog.build()


class TestProfileEditor:
    def test_tables_roundtrip(self, app):
        config = load_station(EXAMPLE)
        config.roles["sis1"] = RoleConfig(
            "sis_block",
            channel="DEV4",
            metadata={"calibration_coefficients": {"VoltageStep": 1e-5}},
        )
        editor = ProfileEditor(config)
        assert editor.config() == config

    def test_yaml_tab_sync_and_errors(self, app):
        editor = ProfileEditor(load_station(EXAMPLE))
        editor.tabs.setCurrentIndex(2)
        text = editor.yaml.toPlainText().replace("name: 2sb", "name: edited")
        editor.yaml.setPlainText(text)
        editor.tabs.setCurrentIndex(0)
        assert editor.name.text() == "edited"
        editor.tabs.setCurrentIndex(2)
        editor.yaml.setPlainText("roles: [")
        assert editor.validate() is None and "invalid YAML" in editor.problems.text()

    def test_unknown_driver_and_save(self, app, tmp_path):
        editor = ProfileEditor(load_station(EXAMPLE), str(tmp_path / "out.yaml"))
        editor.add_instrument("extra", {"driver": "acme.thing"})
        assert editor.validate() is None and "acme.thing" in editor.problems.text()
        editor.instruments.removeRow(editor.instruments.rowCount() - 1)
        editor.add_role("spare", {"instrument": "nrx"})
        editor.save()
        saved = load_station(tmp_path / "out.yaml")
        assert saved.roles["spare"].instrument == "nrx"

    def test_cells(self):
        assert flow("DEV4") == "DEV4" and flow(2) == "2" and flow("2") == "'2'"
        assert flow({"kind": "socket", "port": 5025}) == "{kind: socket, port: 5025}"
        assert flow(None) == ""


class TestSisPanel:
    def test_calibration_save_and_write(
        self, tmp_session, own_profile, monkeypatch, wait
    ):
        from thzdaq_gui.panels.sis_panel import SisPanel

        panel = SisPanel(tmp_session)
        panel.biasRole.setCurrentText("sis2")
        shown = json.loads(panel.editor.toPlainText())
        assert shown == default_sis_calibration("DEV2")

        shown["VoltageStep"] = "1e-5 * 2"
        panel.editor.setPlainText(json.dumps(shown))
        panel.save_to_profile()
        stored = (
            load_station(own_profile).roles["sis2"].metadata["calibration_coefficients"]
        )
        assert stored["VoltageStep"] == "1e-5 * 2"

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        panel.write_to_block()
        channel = tmp_session.station.instrument("sis_block").channel("DEV2")
        wait(lambda: channel.calibration is not None)
        assert channel.calibration == evaluate_sis_calibration(stored)
        assert channel.calibration["VoltageStep"] == pytest.approx(2e-5)

    def test_demagnetization_from_the_panel(self, tmp_session, wait):
        from thzdaq_gui.panels.sis_panel import SisPanel

        panel = SisPanel(tmp_session)
        assert panel.coilRole.currentText() == "sis1_ctrl"
        panel.step.setValue(10)
        panel.delay.setValue(0)
        finished = []
        tmp_session.runner.finished.connect(finished.append)
        panel.btnDemag.click()
        wait(lambda: finished)
        assert (
            finished[0].status == COMPLETED
            and finished[0].procedure == "sis.demagnetize"
        )
        coil = tmp_session.station.instrument("sis_block").ctrl("DEV3")
        assert coil.get_current() == pytest.approx(0, abs=1e-12)


class TestMonitorPanel:
    def test_records_and_plots(self, tmp_session, wait):
        from PySide6.QtCore import Qt
        from thzdaq_gui.panels.monitor_panel import MonitorPanel

        panel = MonitorPanel(tmp_session)
        for i in range(panel.roles.count()):
            item = panel.roles.item(i)
            if item.text() in ("detector", "sis1"):
                item.setCheckState(Qt.Checked)
        panel.interval.setValue(0.05)
        panel.duration.setValue(0.3)
        panel.record.setChecked(True)
        finished = []
        panel.runner.finished.connect(finished.append)
        panel.btnStart.click()
        wait(lambda: finished)
        dataset = finished[0]
        assert dataset.status == COMPLETED and os.path.exists(dataset.metadata["path"])
        power_plot = panel.plots.plots[0]
        assert list(power_plot.curves) == [("detector",)]
        voltage_plot = panel.plots.plots[2]
        assert list(voltage_plot.curves) == [("sis1",)]

    def test_runs_alongside_a_measurement(self, tmp_session, wait):
        from PySide6.QtCore import Qt
        from thzdaq_gui.panels.monitor_panel import MonitorPanel

        panel = MonitorPanel(tmp_session)
        panel.roles.item(0).setCheckState(Qt.Checked)
        panel.interval.setValue(0.05)
        panel.btnStart.click()
        wait(lambda: panel.runner.running)
        finished = []
        tmp_session.runner.finished.connect(finished.append)
        tmp_session.runner.start(
            tmp_session.station, None,
            IVCurve(voltage=(0, 2e-3, 3), settle_time=0, first_point_delay=0),
            {"bias": "sis1"},
        )  # fmt: skip
        wait(lambda: finished)
        assert finished[0].status == COMPLETED and panel.runner.running
        panel.btnStop.click()
        wait(lambda: not panel.runner.running)
