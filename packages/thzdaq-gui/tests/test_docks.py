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
        titles = [e.title for e in window.dock_entries() if e.section == "Devices"]
        assert "SIS1" in titles and "IF switch supply" in titles

    def test_device_menu_is_a_tree_by_type(self, window):
        navigator = window.navigators["Devices"]
        navigator.prepare()
        top = [
            navigator.tree.topLevelItem(i).text(0)
            for i in range(navigator.tree.topLevelItemCount())
        ]
        # Several devices of a type share a branch, a single one stays a row
        assert "SIS bias  (2)" in top and "SIS coil  (2)" in top
        assert "Power supply  (2)" in top and "SIS1" not in top
        assert "R&S NRX" in top  # the only power meter
        group = navigator.tree.topLevelItem(top.index("SIS bias  (2)"))
        assert [group.child(i).text(0) for i in range(group.childCount())] == [
            "SIS1",
            "SIS2",
        ]
        assert not group.isExpanded()
        navigator.clicked(group, 0)
        assert group.isExpanded()
        # The branch stays open the next time the menu opens
        navigator.prepare()
        group = navigator.tree.topLevelItem(top.index("SIS bias  (2)"))
        assert group.isExpanded()
        measures = window.navigators["Measures"]
        measures.prepare()
        assert "2SB  (5)" in [
            measures.tree.topLevelItem(i).text(0)
            for i in range(measures.tree.topLevelItemCount())
        ]

    def test_search_finds_docks_flat(self, window):
        navigator = window.navigators["Devices"]
        navigator.prepare()
        navigator.search.setText("sis2")
        found = [item.text(0) for item in navigator.items()]
        assert found == ["SIS2", "SIS2 coil"]
        assert navigator.items()[0].text(1) == "Devices › SIS bias"
        # Words in any order, the type included
        navigator.search.setText("supply power")
        assert len(navigator.items()) == 2
        navigator.search.setText("nothing like this")
        assert navigator.items() == []

    def test_click_shows_a_dock_and_the_eye_closes_it(self, window):
        navigator = window.navigators["Graphs"]
        navigator.prepare()
        navigator.search.setText("Tn-V")
        item = navigator.item("graph:Tn-V")
        dock = window.docks["graph:Tn-V"]
        assert dock.isClosed() and window.dock_state("graph:Tn-V") == "closed"
        shown = []
        navigator.activated.connect(shown.append)
        navigator.clicked(item, 0)
        assert not dock.isClosed() and dock.isCurrentTab()
        assert shown == ["graph:Tn-V"] and window.dock_state("graph:Tn-V") == "front"
        # Behind another tab: a click brings it forward instead of closing it
        other = window.docks["graph:I-V"]
        window.dock_manager.addDockWidgetTabToArea(dock, other.dockAreaWidget())
        other.setAsCurrentTab()
        assert window.dock_state("graph:Tn-V") == "behind"
        navigator.clicked(navigator.item("graph:Tn-V"), 0)
        assert dock.isCurrentTab() and not dock.isClosed()
        # Only the eye closes it, and opens it again
        navigator.clicked(navigator.item("graph:Tn-V"), 2)
        assert dock.isClosed()
        navigator.clicked(navigator.item("graph:Tn-V"), 2)
        assert not dock.isClosed()

    def test_shown_docks_flash_and_side_bars_unfold(self, window):
        from thzdaq_gui.navigator import Flash

        window.show_dock("data")
        dock = window.docks["data"]
        assert dock.isAutoHide() and dock.autoHideDockContainer().isVisible()
        assert window.dock_state("data") == "front"
        assert dock.findChildren(Flash)

    def test_quick_find_lists_every_dock(self, window):
        window.quickFind.popup()
        navigator = window.quickFind.navigator
        sections = [
            navigator.tree.topLevelItem(i).text(0)
            for i in range(navigator.tree.topLevelItemCount())
        ]
        assert sections == ["Base", "Devices", "Measures", "Graphs"]
        navigator.search.setText("p-v")
        assert navigator.tree.currentItem().data(0, Qt.UserRole) == "graph:P-V"
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        navigator.eventFilter(
            navigator.search, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        )
        assert window.dock_state("graph:P-V") == "front"
        assert not window.quickFind.isVisible()

    def test_menu_states_follow_the_default_layout(self, window):
        # ADS opens the first dock of each area without viewToggled
        wrong = [
            name
            for name, dock in window.docks.items()
            if (window.dock_state(name) == "closed") != dock.isClosed()
        ]
        assert wrong == []
        assert window.dock_state("graph:I-V") != "closed"

    def test_docks_open_with_their_kind(self, window):
        # Default layout: SIS biases open at the bottom, graphs in the centre
        bias_area = window.docks["device:sis_bias_1"].dockAreaWidget()
        supply = window.docks["device:power_supply_1"]
        assert supply.isClosed()
        window.show_dock("device:power_supply_1")
        assert not supply.isClosed() and supply.dockAreaWidget() is bias_area
        assert supply.isCurrentTab()
        assert window.dock_state("device:power_supply_1") == "front"

    def test_custom_graph_rename_delete_and_keep(self, window, session, monkeypatch):
        from thzdaq_gui.graphs import Axis
        from thzdaq_gui.main_window import MainWindow

        hub = window.hub
        graph = hub.new_graph("Mine")
        dock = window.docks["graph:custom1"]
        window.raise_graph(graph)
        # Joins the graphs on screen instead of opening anywhere
        assert dock.dockAreaWidget() is window.docks["graph:I-V"].dockAreaWidget()
        assert dock.isCurrentTab()
        hub.rename(graph, "Mine 2")
        graph.set_axes(Axis("Voltage"), Axis("Current"))
        hub.custom_changed.emit()
        assert hub.graphs["Mine 2"] is graph and "Mine" not in hub.graphs
        assert dock.windowTitle() == "Mine 2"
        assert window.entries["graph:custom1"].title == "Mine 2"
        with pytest.raises(ValueError):
            hub.rename(graph, "I-V")  # a graph of the procedures
        window.save_state()
        again = MainWindow(session, window.settings.fileName(), check_updates=False)
        kept = again.hub.graphs["Mine 2"]
        assert kept.custom and kept.key == "custom1" and kept.y.label == "Current"
        again.confirm_exit = False
        again.close()
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        graph.delete_clicked.emit(graph)
        assert "Mine 2" not in hub.graphs and "graph:custom1" not in window.docks
        assert hub.custom_graphs() == []
        assert not hasattr(hub.graph("I-V"), "btnDelete")  # built-in graphs stay

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
            "active",
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
        # Active is the opposite of the block's short: off shorts the output
        active = next(q for q in panel.quantities if q.key == "active")
        panel.write(active, True)
        wait(lambda: panel.toggles["active"].isChecked())
        channel = session.station.instrument("sis_block_1").channel("DEV4")
        assert not channel.get_short()
        panel.write(active, False)
        wait(lambda: not panel.toggles["active"].isChecked())
        assert channel.get_short()

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

    def test_coil_monitor_shows_the_current(self, window, session, wait):
        """The coil had only its setpoint field: Monitor showed nothing new."""
        panel = window.docks["device:sis_coil_1"].widget().panels[0]
        coil = session.station.device("sis_coil_1")
        coil.set_current(2.5e-3)  # e.g. a demagnetization left it there
        label = panel.values["coil_current"]
        assert label.property("role") == "value"  # orange, as the bias values
        assert panel.displays["coil_current"].prefix() == "m"
        panel.interval.setValue(0.1)
        panel.monitor.setChecked(True)
        wait(lambda: label.text() == "2.5 mA")
        coil.set_current(1e-3)
        wait(lambda: label.text() == "1 mA")
        panel.monitor.setChecked(False)

    def test_device_docks_use_their_instrument_queue(self, window):
        sis = window.docks["device:sis_bias_1"].widget().panels[0]
        meter = window.docks["device:power_meter_1"].widget().panels[0]
        supply = window.docks["device:power_supply_1"].widget().panels
        assert (sis.lane, meter.lane) == ("sis_block_1", "power_meter_1")
        assert {panel.lane for panel in supply} == {"power_supply_1"}  # channels too

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

    def test_measured_iv_can_be_analyzed(self, window, wait):
        from thzdaq_gui.docks.measure import ProcedureBox

        widget = window.docks["device:sis_bias_1"].widget()
        box = widget.findChildren(ProcedureBox)[0]
        box.form.set_values({**FAST_IV, "voltage": Sweep(0, 7e-3, 141)})
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        wait(lambda: finished)
        bar = window.hub.graph("I-V").analysis
        # The curve of the run is offered (the list stayed empty before)
        assert bar.curve.count() == 1
        assert bar.curve.currentData()[0] == finished[0].id
        result = bar.analyze()
        assert result is not None and result.rn_ohm > 0, bar.label.text()
        window.hub.graph("I-V").clear()
        assert bar.curve.count() == 0 and not bar.overlay.items


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
        # ... the others with data are on screen too, in the graphs' tab group
        v_t, p_t = window.docks["graph:V-t"], window.docks["graph:P-t"]
        assert not v_t.isClosed() and not p_t.isClosed() and p_t.isCurrentTab()
        assert v_t.dockAreaWidget() is p_t.dockAreaWidget()
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


class TestFolding:
    def test_controls_stay_below_the_scrolling_setup(self, window):
        box = window.docks["measure:two_sb.tn"].widget().box
        setup = box.scroll.widget()
        assert (
            box.devices_box.parent() is setup and box.parameters_box.parent() is setup
        )
        for control in (
            box.btnStart,
            box.btnStop,
            box.comment,
            box.progress,
            box.state,
        ):
            assert not setup.isAncestorOf(control) and box.footer.isAncestorOf(control)

    def test_folded_devices_say_which_are_chosen(self, window, session):
        box = window.docks["measure:sis.pv_curve"].widget().box
        box.devices_box.set_expanded(False)
        summary = box.devices_box.summary
        assert summary.isVisibleTo(box) and "SIS1" in summary.text()
        assert not box.devices_box.body.isVisibleTo(box)
        # Remembered for the next dock of this procedure
        again = type(box)(session, window.hub, box.procedure_class)
        assert not again.devices_box.expanded()
        box.devices_box.set_expanded(True)

    def test_a_missing_device_unfolds_the_devices(self, window, monkeypatch):
        box = window.docks["measure:sis.iv_curve"].widget().box
        box.devices_box.set_expanded(False)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
        box.devices.combos["bias"].setCurrentIndex(-1)
        box.start()
        assert box.devices_box.expanded()

    def test_device_scans_are_folded_and_tell_how_they_run(self, window, wait):
        from thzdaq_gui.collapsible import Collapsible
        from thzdaq_gui.docks.measure import ProcedureBox

        widget = window.docks["device:sis_bias_1"].widget()
        section = next(
            s for s in widget.findChildren(Collapsible) if s.title() == "I-V scan"
        )
        assert not section.expanded()
        box = section.findChildren(ProcedureBox)[0]
        box.form.set_values(FAST_IV)
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        wait(lambda: finished and not box.ui_running)
        assert section.summary.text() == f"completed #{finished[0].id}"
        # The folded log shows its last line
        assert box.log_box.summary.text().startswith("saved ")
