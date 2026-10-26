import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from thzdaq_core.data import COMPLETED, read_json
from thzdaq_core.measurements.parameters import Sweep
from thzdaq_core.measurements.registry import list_procedures
from thzdaq_core.station import load_station
from thzdaq_gui.docks.setup import DeviceDialog, InstrumentDialog
from thzdaq_instruments.transport.base import PROLOGIX

FAST_IV = {"voltage": Sweep(0, 5e-3, 6), "settle_time": 0.0, "first_point_delay": 0.0}


class TestWindow:
    def test_docks_like_the_old_app(self, window):
        names = set(window.docks)
        assert {"setup", "data", "log"} <= names
        assert {f"measure:{cls.name}" for cls in list_procedures()} <= names
        assert {"graph:I-V", "graph:P-V", "graph:P-IF", "graph:Tn upper"} <= names
        # Instruments and configured devices get docks; fixed channels live inside
        assert {"device:sis_bias_1", "device:sis_coil_2", "device:signal_generator_1",
                "device:power_supply_1", "device:power_meter_1"} <= names  # fmt: skip
        assert not any(name.startswith("device:power_supply_1:") for name in names)
        menus = [a.text() for a in window.menuBar().actions()]
        assert menus == ["&File", "&Base", "&Devices", "&Measures", "&Graphs", "&Help"]
        titles = [a.text() for a in window.menuDevices.actions()]
        assert "SIS1" in titles and "IF switch supply" in titles

    def test_menus_show_checks_and_bring_docks_forward(self, window):
        action = window.menu_actions["graph:Tn-V"]
        assert action.isCheckable() and action.icon().isNull()
        assert not action.isChecked()
        action.trigger()
        dock = window.docks["graph:Tn-V"]
        assert not dock.isClosed() and action.isChecked()
        # Behind another tab: the menu brings it forward instead of closing it
        other = window.docks["graph:I-V"]
        window.dock_manager.addDockWidgetTabToArea(dock, other.dockAreaWidget())
        other.setAsCurrentTab()
        assert not dock.isCurrentTab()
        action.trigger()
        assert dock.isCurrentTab() and action.isChecked()
        action.trigger()
        assert dock.isClosed() and not action.isChecked()

    def test_menu_checks_follow_the_default_layout(self, window):
        # ADS opens the first dock of each area without viewToggled
        wrong = [
            name
            for name, dock in window.docks.items()
            if window.menu_actions[name].isChecked() == dock.isClosed()
        ]
        assert wrong == []
        assert window.menu_actions["graph:I-V"].isChecked()

    def test_area_close_button_closes_one_tab(self, window):
        import PySide6QtAds as QtAds

        assert QtAds.CDockManager.testConfigFlag(
            QtAds.CDockManager.DockAreaCloseButtonClosesTab
        )

    def test_no_dock_for_an_instrument_without_controls(self, window):
        assert "device:sis_block_1" not in window.docks
        assert (
            "device:sis_bias_1" in window.docks and "device:chopper_1" in window.docks
        )

    def test_device_docks_follow_the_setup(self, window, session, profile, monkeypatch):
        setup = window.setupWidget
        monkeypatch.setattr(DeviceDialog, "exec", lambda self: QDialog.Accepted)

        def fill(dialog_self):
            dialog_self.kind.setCurrentIndex(dialog_self.kind.findData("sis_bias"))
            dialog_self.channel.setCurrentIndex(dialog_self.channel.findData("DEV1"))
            dialog_self.title.setText("SIS b2d2")
            return QDialog.Accepted

        monkeypatch.setattr(DeviceDialog, "exec", fill)
        setup.add_device("sis_block_1")
        assert "device:sis_bias_3" in window.docks
        saved = load_station(profile).instruments["sis_block_1"].devices["sis_bias_3"]
        assert (saved.kind, saved.channel, saved.title) == (
            "sis_bias",
            "DEV1",
            "SIS b2d2",
        )
        assert "sis b2d2" in setup.cards["sis_block_1"].search_text

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        setup.delete_device("sis_block_1", "sis_bias_3")
        assert "device:sis_bias_3" not in window.docks
        setup.delete_instrument("power_supply_2")
        assert "device:power_supply_2" not in window.docks
        assert "device:yig_power_1" not in window.docks
        assert "power_supply_2" not in load_station(profile).instruments

    def test_add_instrument_dialog(self, window, session, profile, monkeypatch):
        def fill(dialog_self):
            dialog_self.driver.setCurrentIndex(dialog_self.driver.findData("rs.nrx"))
            dialog_self.title.setText("Second NRX")
            dialog_self.connection.host.setText("10.0.0.7")
            return QDialog.Accepted

        monkeypatch.setattr(InstrumentDialog, "exec", fill)
        window.setupWidget.add_instrument()
        spec = load_station(profile).instruments["power_meter_2"]
        assert spec.title == "Second NRX" and spec.connection.host == "10.0.0.7"
        assert spec.connection.port == 5025  # from the recommended connection
        assert "device:power_meter_2" in window.docks

    def test_connection_editor_shows_fields_of_the_kind(self, app, session):
        dialog = InstrumentDialog(session.station.config, "signal_generator_1")
        editor = dialog.connection
        assert editor.kind.currentData() == PROLOGIX
        assert editor.gpib.value() == 19 and not editor.gpib.isHidden()
        assert editor.serial_port.isHidden()
        assert not dialog.driver.isEnabled()
        assert dialog.instrument().connection.gpib == 19

    def test_driver_list_has_no_simulators_or_pfeiffer(self, app, session):
        dialog = InstrumentDialog(session.station.config)
        keys = [dialog.driver.itemData(i) for i in range(dialog.driver.count())]
        assert "rigol.dp832a" in keys and "scontel.sis_block" in keys
        assert not [k for k in keys if k.startswith(("sim.", "pfeiffer."))]

    def test_long_profile_path_wraps(self, app):
        from thzdaq_gui.docks.setup import breakable_path

        path = r"C:\Users\Snake\Desktop\ThzDAQ_Windows_x64\ThzDAQ\stations\lab.yaml"
        text = breakable_path(path)
        assert text.replace("\u200b", "") == path and text.count(
            "\u200b"
        ) == path.count("\\")

    def test_docks_are_not_wider_than_their_rows_need(self, window):
        # Number boxes sized for their range made these 700-820 px wide
        for name in ("device:sis_bias_1", "measure:two_sb.tn"):
            dock = window.docks[name]
            dock.toggleView(True)
            content = dock.widget().content().widget()
            assert content.minimumSizeHint().width() < 620, name
        assert window.setupWidget.minimumSizeHint().width() < 450

    def test_editing_keeps_a_driver_no_longer_offered(self, app):
        from thzdaq_core.station import InstrumentConfig, StationConfig
        from thzdaq_instruments.transport import SERIAL, ConnectionSpec

        spec = ConnectionSpec(SERIAL, serial_port="COM3")
        config = StationConfig(
            "bench", {"gauge": InstrumentConfig("pfeiffer.gauge", spec, title="G")}
        )
        dialog = InstrumentDialog(config, "gauge")
        assert dialog.driver_key() == "pfeiffer.gauge"
        assert dialog.instrument().driver == "pfeiffer.gauge"

    def test_connect_reports_identity(self, window, wait):
        window.setupWidget.connect_instrument("sis_block_1")
        card = window.setupWidget.cards["sis_block_1"]
        wait(lambda: card.status.text().startswith("OK"))
        assert "SimSisBlock" in card.status.text()


class TestDeviceDocks:
    def test_quantity_panel_reads_and_sets(self, window, session, wait):
        widget = window.docks["device:sis_bias_1"].widget()
        panel = widget.panels[0]
        assert [q.key for q in panel.quantities] == [
            "voltage_set",
            "voltage",
            "current",
            "short",
        ]
        # A setpoint is its field: no reading of it, polled only once
        assert "voltage_set" not in panel.values and "voltage" in panel.values
        voltage = next(q for q in panel.quantities if q.key == "voltage_set")
        panel.write(voltage, 2.5e-3)
        wait(lambda: panel.values["voltage"].text().startswith("2.5"))
        assert panel.values["voltage"].text() == "2.5 mV"
        assert panel.fields["voltage_set"].value() == pytest.approx(2.5e-3)
        assert not panel.polled(voltage) and panel.polled(panel.quantities[1])
        # The setpoint is remembered for the next start, not written on it
        from thzdaq_gui.settings import settings

        assert float(settings().value("setpoints/sis_bias_1/voltage_set")) == 2.5e-3
        short = next(q for q in panel.quantities if q.key == "short")
        panel.write(short, True)
        wait(lambda: panel.toggles["short"].isChecked())
        assert session.station.instrument("sis_block_1").channel("DEV4").get_short()

    def test_generator_configuration_from_the_profile(
        self, window, session, profile, wait
    ):
        dock = window.docks["device:signal_generator_1"]
        widget = dock.widget()
        config = next(p for p in widget.panels if p.config)
        main = widget.panels[0]
        assert [q.key for q in config.quantities][:2] == [
            "frequency_multiplier",
            "oem_state",
        ]
        assert "frequency" in [q.key for q in main.quantities]
        # Filled from the profile, nothing written yet
        field = config.fields["frequency_multiplier"]
        assert field.value() == 18 and not field.pending
        generator = session.station.instrument("signal_generator_1")
        generator.set_frequency_multiplier(9)  # changed on the front panel
        config.read()
        wait(lambda: not config.notes["frequency_multiplier"].isHidden())
        assert "device: 9" in config.notes["frequency_multiplier"].text()
        assert generator.get_frequency_multiplier() == 9  # connecting wrote nothing
        # Set writes the device and the profile; the dock is not rebuilt
        config.apply(
            next(q for q in config.quantities if q.key == "frequency_multiplier")
        )
        wait(lambda: generator.get_frequency_multiplier() == 18)
        wait(lambda: config.notes["frequency_multiplier"].isHidden())
        assert dock.widget() is widget
        field.set_value(12, pending=True)
        config.apply(
            next(q for q in config.quantities if q.key == "frequency_multiplier")
        )
        wait(lambda: load_station(profile).instruments["signal_generator_1"].settings
             == {"frequency_multiplier": 12})  # fmt: skip
        assert dock.widget() is widget and not field.pending
        # Take from device keeps the front-panel value: profile only, no write
        generator.set_frequency_multiplier(6)
        config.read()
        wait(lambda: not config.notes["frequency_multiplier"].isHidden())
        config.notes["frequency_multiplier"].linkActivated.emit("take")
        wait(lambda: load_station(profile).instruments["signal_generator_1"].settings
             == {"frequency_multiplier": 6})  # fmt: skip
        assert field.value() == 6 and not field.pending
        assert config.notes["frequency_multiplier"].isHidden()

    def test_fields_take_values_in_the_chosen_prefix(self, window, session, wait):
        main = window.docks["device:signal_generator_1"].widget().panels[0]
        field = main.fields["frequency"]
        assert field.prefix.prefix() == "G" and "×10⁹" in field.prefix.currentText()
        field.spin.setValue(223.5)
        assert field.pending and field.value() == 223.5e9
        field.prefix.setCurrentIndex(field.prefix.findData("M"))
        assert field.spin.value() == 223500.0 and field.value() == 223.5e9
        field.apply_requested.emit()  # Enter
        generator = session.station.instrument("signal_generator_1")
        wait(lambda: generator.get_frequency() == 223.5e9)
        wait(lambda: not field.pending)
        sis = window.docks["device:sis_bias_1"].widget().panels[0]
        assert sis.fields["voltage_set"].prefix.prefix() == "m"
        assert sis.displays["current"].prefix() == "µ"

    def test_chopper_dock(self, window, session, wait):
        from thzdaq_gui.docks.devices import ChopperGroup

        widget = window.docks["device:chopper_1"].widget()
        main = widget.panels[0]
        assert [q.key for q in main.quantities] == ["load_state", "running"]
        group = widget.findChildren(ChopperGroup)[0]
        chopper = session.station.instrument("chopper_1")
        group.run(lambda d: d.to_hot())
        wait(lambda: main.values["load_state"].text() == "hot")
        group.frequency.setValue(5.5)
        group.start()
        wait(lambda: chopper.running and main.toggles == {} and
             main.values["running"].text() == "ON")  # fmt: skip
        assert chopper.frequency == 5.5
        group.btnStop.click()
        wait(lambda: not chopper.running)

    def test_instrument_dock_has_its_channels(self, window):
        widget = window.docks["device:power_supply_1"].widget()
        assert [p.ref for p in widget.panels] == [
            "power_supply_1", "power_supply_1:1", "power_supply_1:2", "power_supply_1:3",
        ]  # fmt: skip

    def test_monitor_plots_to_time_graphs(self, window, wait):
        panel = window.docks["device:power_meter_1"].widget().panels[0]
        panel.interval.setValue(0.1)
        raised = []
        window.hub.raise_requested.connect(lambda w: raised.append(w.title))
        panel.plot.setChecked(True)
        panel.monitor.setChecked(True)
        graph = window.hub.graph("P-t")
        wait(lambda: graph.items and len(next(iter(graph.points.values()))) >= 2)
        panel.monitor.setChecked(False)
        key = ("monitor", "power_meter_1", "power")
        assert graph.curve_label(key) == "R&S NRX Power"
        assert raised == ["P-t"]  # once, not on every reading

    def test_sis_bias_offsets_and_calibration(
        self, window, session, profile, wait, monkeypatch
    ):
        from thzdaq_gui.docks.devices import SisBiasGroup

        widget = window.docks["device:sis_bias_2"].widget()

        group = widget.findChildren(SisBiasGroup)[0]
        field = group.offset_voltage
        assert field.prefix.symbol() == "µV"  # same field as the rest of the dock
        field.set_value(1e-4, pending=True)
        assert field.spin.value() == pytest.approx(100.0)
        field.apply_requested.emit()  # Enter saves
        assert not field.pending
        assert load_station(profile).instruments["sis_block_1"].devices[
            "sis_bias_2"
        ].settings["offset_voltage"] == pytest.approx(1e-4)
        # The dock was rebuilt for the new settings; the device uses them
        wait(lambda: True)
        assert session.station.device("sis_bias_2").offset_voltage == pytest.approx(
            1e-4
        )

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        shown = []
        monkeypatch.setattr(
            QMessageBox, "information", lambda *a, **k: shown.append(a[2])
        )
        group = window.docks["device:sis_bias_2"].widget().findChildren(SisBiasGroup)[0]
        group.write_calibration()
        wait(lambda: shown)
        channel = session.station.instrument("sis_block_1").channel("DEV2")
        assert channel.calibration["VoltageStep"] == pytest.approx(1e-5)

    def test_iv_scan_in_the_device_dock(self, window, session, wait):
        from thzdaq_gui.docks.measure import ProcedureBox

        widget = window.docks["device:sis_bias_1"].widget()
        box = widget.findChildren(ProcedureBox)[0]
        assert box.fixed == {"bias": "sis_bias_1"} and box.devices_box.isHidden()
        box.form.set_values(FAST_IV)
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        wait(lambda: finished)
        assert finished[0].status == COMPLETED
        assert len(window.hub.graph("I-V").items) == 1


class TestMeasureAndData:
    def test_saved_parameters_survive_a_dropped_one(self, window, session):
        from thzdaq_core.measurements.registry import get_procedure
        from thzdaq_gui.docks.measure import ProcedureBox
        from thzdaq_gui.settings import settings

        cls = get_procedure("two_sb.pump_balance")
        saved = {"bias_delay": 0.7, "upper_when_on": False}  # no longer a parameter
        key = f"procedures/{cls.name}"
        settings().setValue(key, json.dumps({"parameters": saved, "devices": {}}))
        try:
            box = ProcedureBox(session, window.hub, cls)
            assert box.form.values()["bias_delay"] == pytest.approx(0.7)
        finally:
            settings().remove(key)

    def test_measurement_dock_flow(self, window, session, wait, tmp_path):
        box = window.docks["measure:sis.iv_curve"].widget().box
        box.form.set_values(FAST_IV)
        box.devices.combos["bias"].setCurrentIndex(
            box.devices.combos["bias"].findData("sis_bias_2")
        )
        box.comment.setText("smoke test")
        finished = []
        box.runner.finished.connect(finished.append)
        box.btnStart.click()
        wait(lambda: finished and box.btnStart.isEnabled())
        measurement = finished[0]
        assert measurement.status == COMPLETED and measurement.comment == "smoke test"
        assert measurement.devices["bias"].ref == "sis_bias_2"
        graph = window.hub.graph("I-V")
        (key,) = graph.items
        assert graph.curve_label(key).startswith("#1 SIS2")
        model = session.measurements
        assert model.rowCount() == 1 and model.data(model.index(0, 5)) == COMPLETED
        saved = read_json(measurement.metadata["path"])
        assert saved.tables["iv"].data["voltage"][0] == 0.0
        # Comments edited in the table go to the file at once
        model.setData(model.index(0, 2), "edited")
        assert read_json(measurement.metadata["path"]).comment == "edited"
        # The next start remembers the devices and parameters
        again = type(box)(session, window.hub, box.procedure_class)
        assert again.devices.mapping()["bias"] == "sis_bias_2"
        assert again.form.values()["voltage"] == FAST_IV["voltage"]

    def test_data_dock_opens_plots_and_exports(
        self, window, session, wait, tmp_path, monkeypatch
    ):
        from thzdaq_core.data import Measurement, MeasurementStore

        measurement = Measurement("sis.iv_curve", title="SIS I-V curve")
        for v in (1e-3, 2e-3):
            measurement.append("iv", {"voltage": v, "current": v / 20})
        path = MeasurementStore(tmp_path / "other").save(measurement)
        data = window.dataWidget
        monkeypatch.setattr(
            "thzdaq_gui.docks.data.QFileDialog.getOpenFileNames",
            lambda *a, **k: ([str(path)], ""),
        )
        data.open_files()
        assert session.measurements.rowCount() == 1
        assert len(window.hub.graph("I-V").items) == 1
        data.table.selectRow(0)
        csv_path = tmp_path / "iv.csv"
        monkeypatch.setattr(
            "thzdaq_gui.docks.data.QFileDialog.getSaveFileName",
            lambda *a, **k: (str(csv_path), ""),
        )
        data.export()
        assert (
            csv_path.read_text(encoding="utf-8")
            .splitlines()[0]
            .startswith('"Voltage, V"')
        )

    def test_monitor_dock_watches_ticked_values(self, window, session, wait):
        box = window.docks["measure:monitor.time"].widget().box
        box.set_device("power_meter_1", True)
        box.set_device("sis_bias_1", True)
        assert sorted(box.entries()) == [
            "power_meter_1/power",
            "sis_bias_1/current",
            "sis_bias_1/voltage",
        ]
        # Expand the SIS bias and keep only the voltage
        bias = next(
            i for i in box.device_items() if i.data(0, Qt.UserRole) == "sis_bias_1"
        )
        current = next(
            bias.child(i)
            for i in range(bias.childCount())
            if bias.child(i).data(0, Qt.UserRole) == "current"
        )
        current.setCheckState(0, Qt.Unchecked)
        box.form.editors["interval"].set(0.05)
        box.form.editors["duration"].set(0.2)
        box.form.editors["window"].set(60)
        raised = []
        window.hub.raise_requested.connect(lambda w: raised.append(w.title))
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        wait(lambda: finished)
        samples = finished[0].records("samples")
        assert {(s["device"], s["key"]) for s in samples} == {
            ("R&S NRX", "power"),
            ("SIS1", "voltage"),
        }
        assert window.hub.graph("P-t").items and window.hub.graph("V-t").items
        assert not window.hub.graph("p-t").items
        assert raised == ["P-t"]  # one graph to the front: the first with data
        assert box.window == 60
        assert isinstance(finished[0].id, int)
        # The choice is remembered
        box.refresh_devices()
        assert sorted(box.entries()) == ["power_meter_1/power", "sis_bias_1/voltage"]


class TestPerspectives:
    def test_create_save_and_restore(self, session, tmp_path, monkeypatch):
        from thzdaq_gui.main_window import MainWindow

        settings = str(tmp_path / "layout.ini")
        window = MainWindow(
            session, settings, restore_layout=False, check_updates=False
        )
        window.show()
        assert "Default" in window.dock_manager.perspectiveNames()
        window.docks["graph:Tn-V"].toggleView(True)
        monkeypatch.setattr(
            "thzdaq_gui.main_window.QInputDialog.getText",
            lambda *a, **k: ("Noise", True),
        )
        window.create_perspective()
        assert window.perspectives.currentText() == "Noise"
        window.docks["graph:Tn-V"].toggleView(False)
        window.open_perspective("Noise")
        assert not window.docks["graph:Tn-V"].isClosed()
        window.close()

        again = MainWindow(session, settings, check_updates=False)
        assert set(again.dock_manager.perspectiveNames()) >= {"Default", "Noise"}
        assert not again.docks["graph:Tn-V"].isClosed()
        again.close()

    def test_switching_keeps_widths_and_holds_only_open_contents(self, window, app):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QSplitter
        from thzdaq_gui.docks.body import DockBody

        def settle():
            for _ in range(5):
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        def widths():
            return sorted(
                str(s.sizes())
                for s in window.dock_manager.findChildren(QSplitter)
                if s.isVisible()
            )

        window.resize(1500, 900)
        settle()
        for splitter in window.dock_manager.findChildren(QSplitter):
            if splitter.isVisible() and splitter.count() == 2:
                total = sum(splitter.sizes())
                splitter.setSizes([total // 4, total - total // 4])
        settle()
        window.dock_manager.addPerspective("Narrow")
        narrow = widths()
        window.docks["device:power_meter_1"].toggleView(True)
        window.docks["measure:monitor.time"].toggleView(True)
        settle()
        window.dock_manager.addPerspective("Wide")
        wide = widths()
        for name, expected in (("Narrow", narrow), ("Wide", wide), ("Narrow", narrow)):
            window.open_perspective(name)
            settle()
            assert widths() == expected, name
        # Closed device and measurement docks carry no content (fast switching)
        for name, dock in window.docks.items():
            body = dock.widget()
            if isinstance(body, DockBody):
                assert body.attached == (not dock.isClosed()), name
        assert not window.docks["device:power_meter_1"].widget().attached

    def test_settings_keep_the_station_path(self, window, session, tmp_path):
        window.on_station_changed(session.station)
        assert window.settings.value("station/path") == str(session.path)


def test_measurement_json_is_plain(tmp_path):
    from thzdaq_core.data import Measurement, MeasurementStore

    measurement = Measurement("demo")
    measurement.append("t", {"x": 1.0})
    data = json.loads(MeasurementStore(tmp_path).save(measurement).read_text())
    assert data["tables"]["t"]["data"] == {"x": [1.0]}


class TestExit:
    def test_cancel_keeps_the_window(self, window, exit_answer):
        from PySide6.QtWidgets import QDialog

        exit_answer["result"] = QDialog.Rejected
        assert not window.close()
        assert window.isVisible()
        exit_answer["result"] = QDialog.Accepted

    def test_dump_and_state_as_answered(
        self, window, session, wait, tmp_path, exit_answer
    ):
        import json

        box = window.docks["measure:sis.iv_curve"].widget().box
        box.form.set_values(FAST_IV)
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        wait(lambda: finished)
        exit_answer["store"], exit_answer["dump"] = False, True
        assert window.close()
        (dump,) = (tmp_path / "data" / "dumps").glob("dump_*.json")
        data = json.loads(dump.read_text(encoding="utf-8"))
        assert [m["procedure"] for m in data] == ["sis.iv_curve"]
        assert data[0]["tables"]["iv"]["data"]["voltage"][0] == 0.0
        assert window.settings.value("window/docks") is None  # layout not stored

    def test_dialog_defaults(self, app):
        from thzdaq_gui.exit_dialog import ExitDialog

        idle = ExitDialog(running=0, measurements=0)
        assert idle.storeState.isChecked() and not idle.dumpData.isEnabled()
        busy = ExitDialog(running=2, measurements=3)
        assert busy.dumpData.isChecked() and "3" in busy.dumpData.text()


def test_no_stray_windows_flash(app, session, tmp_path):
    """Widgets shown before they have a parent pop up as small windows."""
    import copy

    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget
    from thzdaq_core.station import DeviceConfig
    from thzdaq_gui.main_window import MainWindow

    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Show and isinstance(obj, QWidget):
                if obj.isWindow():
                    shown.append(type(obj).__name__)
            return False

    spy = Spy()
    app.installEventFilter(spy)
    try:
        window = MainWindow(
            session, str(tmp_path / "s.ini"), restore_layout=False, check_updates=False
        )
        window.show()
        config = copy.deepcopy(session.station.config)
        config.instruments["sis_block_1"].devices["sis_bias_3"] = DeviceConfig(
            "sis_bias", channel="DEV1"
        )
        session.update_config(config)
        app.processEvents()
        # Dock contents detached and attached again (closing, perspectives)
        dock = window.docks["device:power_meter_1"]
        dock.toggleView(True)
        dock.toggleView(False)
        window.dock_manager.addPerspective("P")
        dock.toggleView(True)
        window.open_perspective("P")
        app.processEvents()
    finally:
        app.removeEventFilter(spy)
    assert shown == ["MainWindow"]
    window.close()


class TestHangs:
    def test_watchdog_returns_the_dock_to_idle(self, window):
        box = window.docks["measure:sis.iv_curve"].widget().box
        box.on_running(True)  # the dock thinks it runs, the thread is gone
        assert not box.btnStart.isEnabled()
        box.check_thread()  # the end signal may still be queued: wait one more look
        assert not box.btnStart.isEnabled()
        box.check_thread()
        assert box.btnStart.isEnabled() and box.state.text() == "Idle"

    def test_device_that_does_not_answer_is_named_once(
        self, window, monkeypatch, caplog
    ):
        worker = window.session.worker
        monkeypatch.setattr(type(worker), "current", property(lambda s: "Rigol 1"))
        monkeypatch.setattr(type(worker), "started_at", property(lambda s: 1.0))
        monkeypatch.setattr(worker, "busy_for", lambda: 12.0)
        with caplog.at_level("WARNING"):
            window.check_device_worker()
            window.check_device_worker()
        named = [r for r in caplog.records if "Rigol 1 does not answer" in r.message]
        assert len(named) == 1
        assert "Rigol 1" in window.statusBar().currentMessage()

    def test_abort_is_offered_only_while_starting_or_stopping(self, window):
        box = window.docks["measure:sis.iv_curve"].widget().box
        box.on_running(True)
        box.state.setText("Running")
        box.offer_abort()  # a timer of an earlier start or stop
        assert box.btnAbort.isHidden()
        box.stop()
        assert box.stuck.isActive()
        box.on_running(False)
        assert not box.stuck.isActive()

    def test_stop_without_answer_offers_abort(self, window, session, monkeypatch):
        box = window.docks["measure:sis.iv_curve"].widget().box
        aborted = []
        monkeypatch.setattr(
            session.station, "abort", lambda refs: aborted.append(list(refs))
        )
        box.on_running(True)
        box.stop()
        assert box.state.text() == "Stopping..." and box.btnAbort.isHidden()
        box.offer_abort()  # STUCK_AFTER_MS later, still running
        assert not box.btnAbort.isHidden() and "Abort" in box.state.text()
        box.abort()
        assert aborted and "sis_bias" in aborted[0][0]
        box.on_running(False)
        assert box.btnAbort.isHidden()

    def test_start_while_running_warns(self, window, monkeypatch):
        box = window.docks["measure:sis.iv_curve"].widget().box
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
        )
        monkeypatch.setattr(type(box.runner), "running", property(lambda self: True))
        box.start()
        assert warnings and "still running" in warnings[0]

    def test_connections_group(self, app, wait):
        from thzdaq_core.station import InstrumentConfig, Station, StationConfig
        from thzdaq_gui.docks.setup import ConnectionsGroup
        from thzdaq_instruments.transport import SOCKET, ConnectionSpec, TransportPool
        from thzdaq_instruments.transport.fake import FakeLink

        pool = TransportPool(lambda spec: FakeLink({":OUTP? CH1": "ON"}))
        config = StationConfig(
            "bench",
            {"rigol": InstrumentConfig(
                "rigol.dp832a", ConnectionSpec(SOCKET, host="h", port=5555), title="Rigol"
            )},
        )  # fmt: skip
        station = Station(config, pool=pool)
        group = ConnectionsGroup(station)
        (state,) = group.rows.values()
        assert state.text() == "not connected"
        station["rigol:1"].get_output()
        wait(lambda: state.text() == "connected")  # refreshed on its own
        pool.abort(next(iter(group.rows)))
        wait(lambda: state.text() == "error, reconnects")
        group.reset(next(iter(group.rows)))
        wait(lambda: state.text() == "connected")
        station.close()
