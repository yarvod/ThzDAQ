import time
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox
from thzdaq_api.measurement_file import COMPLETED
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_core.domain.measurements.catalog import list_procedures
from thzdaq_core.adapters.yaml_profiles import load_station
from thzdaq_gui.settings import (
    LAYOUT,
    STATION_PATH,
    procedure_key,
    setpoint_key,
)
from thzdaq_gui.docks.setup import DeviceDialog, InstrumentDialog
from thzdaq_instruments.transport.base import PROLOGIX

FAST_IV = {
    "voltage": {"start": 0.0, "stop": 5e-3, "points": 6},
    "settle_time": 0.0,
    "first_point_delay": 0.0,
}


def sweep(start, stop, points):
    return {"start": start, "stop": stop, "points": points}


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
        assert menus == ["&File", "&Devices", "&Measures", "&Graphs", "&Help"]
        titles = [e.title for e in window.docks.listed() if e.section == "Devices"]
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
        assert dock.isClosed() and window.docks.state("graph:Tn-V") == "closed"
        shown = []
        navigator.activated.connect(shown.append)
        navigator.clicked(item, 0)
        assert not dock.isClosed() and dock.isCurrentTab()
        assert shown == ["graph:Tn-V"] and window.docks.state("graph:Tn-V") == "front"
        # Behind another tab: a click brings it forward instead of closing it
        other = window.docks["graph:I-V"]
        window.dock_manager.addDockWidgetTabToArea(dock, other.dockAreaWidget())
        other.setAsCurrentTab()
        assert window.docks.state("graph:Tn-V") == "behind"
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
        assert window.docks.state("data") == "front"
        assert dock.findChildren(Flash)

    def test_quick_find_lists_every_dock(self, window):
        window.quickFind.popup()
        navigator = window.quickFind.navigator
        sections = [
            navigator.tree.topLevelItem(i).text(0)
            for i in range(navigator.tree.topLevelItemCount())
        ]
        assert sections == ["Devices", "Measures", "Graphs"]
        navigator.search.setText("p-v")
        assert navigator.tree.currentItem().data(0, Qt.UserRole) == "graph:P-V"
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        navigator.eventFilter(
            navigator.search, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        )
        assert window.docks.state("graph:P-V") == "front"
        assert not window.quickFind.isVisible()

    def test_menu_states_follow_the_default_layout(self, window):
        # ADS opens the first dock of each area without viewToggled
        wrong = [
            name
            for name, dock in window.docks.items()
            if (window.docks.state(name) == "closed") != dock.isClosed()
        ]
        assert wrong == []
        assert window.docks.state("graph:I-V") != "closed"

    def test_a_dock_without_a_place_opens_floating(self, window, app):
        """A device or measurement dock the person has not placed yet floats
        over the middle of the window, sized for its content."""
        window.resize(1500, 900)
        app.processEvents()
        supply = window.docks["device:power_supply_1"]
        assert supply.isClosed() and supply.dockAreaWidget() is None
        window.show_dock("device:power_supply_1")
        app.processEvents()
        assert not supply.isClosed() and supply.isFloating()
        assert window.docks.state("device:power_supply_1") == "front"
        floating = supply.floatingDockContainer()
        assert floating.geometry().contains(window.geometry().center())
        assert floating.width() >= supply.widget().content().sizeHint().width()
        assert floating.width() <= 0.9 * window.width()
        # Closed floating, it floats again where it was
        where = floating.geometry()
        supply.toggleView(False)
        window.show_dock("device:power_supply_1")
        assert supply.isFloating()
        assert supply.floatingDockContainer().geometry() == where

    def test_a_docked_dock_comes_back_where_it_was(self, window, app):
        """Docked by the person and closed, a dock opens in its place: in its
        tab group, or its group comes back where it was."""
        import PySide6QtAds as QtAds

        iv = window.docks["graph:I-V"]
        supply = window.docks["device:power_supply_1"]
        window.dock_manager.addDockWidget(
            QtAds.BottomDockWidgetArea, supply, iv.dockAreaWidget()
        )
        supply.toggleView(True)
        app.processEvents()
        area = supply.dockAreaWidget()
        place = area.mapTo(window, area.rect().topLeft())
        supply.toggleView(False)
        app.processEvents()
        assert not area.isVisible()  # the group of the closed dock hides
        window.show_dock("device:power_supply_1")
        app.processEvents()
        assert supply.dockAreaWidget() is area and not supply.isFloating()
        assert area.mapTo(window, area.rect().topLeft()) == place
        # A tab of a group with others: back as a tab of it
        bias = window.docks["device:sis_bias_1"]
        group = bias.dockAreaWidget()
        bias.toggleView(False)
        window.show_dock("device:sis_bias_1")
        assert bias.dockAreaWidget() is group and bias.isCurrentTab()

    def test_graphs_are_named_by_their_caption(self, window):
        """The key names the dock (layouts, into=); people read the caption:
        in the dock's title, the graph's own title, the Graphs menu and Ctrl+K."""
        coil = window.docks["graph:Coil-t"]
        assert coil.windowTitle() == "I–t   Coil current (time)"
        assert window.docks["graph:p-t"].windowTitle() == "p–t   Pressure (time)"
        graph = window.hub.graph("I-V")
        assert graph.title == "I-V"
        shown = graph.plot.getPlotItem().titleLabel.text
        assert shown == "I–V&nbsp;&nbsp;&nbsp;SIS current (bias voltage)"
        assert window.docks["graph:I-V"].windowTitle() == graph.caption

    def test_graphs_open_with_their_kind(self, window):
        """A graph not on screen joins the open graphs."""
        tn = window.docks["graph:Tn-V"]
        assert tn.isClosed()
        window.show_dock("graph:Tn-V")
        assert tn.dockAreaWidget() is window.docks["graph:I-V"].dockAreaWidget()
        assert tn.isCurrentTab() and not tn.isFloating()

    def test_base_docks_are_pinned_to_their_side_bars(self, window):
        """Setup and Data on the left, the rest at the bottom; no close
        button, not in the menus or Ctrl+K."""
        import PySide6QtAds as QtAds

        sides = {
            "setup": QtAds.SideBarLeft, "data": QtAds.SideBarLeft,
            "processes": QtAds.SideBarBottom, "log": QtAds.SideBarBottom,
            "daemon": QtAds.SideBarBottom,
        }  # fmt: skip
        for name, side in sides.items():
            dock = window.docks[name]
            assert dock.isAutoHide() and not dock.isClosed(), name
            assert dock.autoHideDockContainer().sideBarLocation() == side, name
            features = dock.features()
            assert not features & QtAds.CDockWidget.DockWidgetClosable, name
            assert name not in window.docks.entries, name
        assert "&Base" not in [m.text() for m in window.menuBar().actions()]
        # The close button of another dock hides it: its values stay
        supply = window.docks["device:power_supply_1"]
        window.show_dock("device:power_supply_1")
        assert supply.features() & QtAds.CDockWidget.DockWidgetClosable
        body = supply.widget()
        supply.toggleView(False)
        assert (
            body.built
            and not body.attached
            and "device:power_supply_1" in (window.docks)
        )

    def test_find_works_from_anywhere_in_the_program(self, window, app):
        """Ctrl+K (Cmd+K on macOS) from a field of a dock, the bar on top and
        a floating dock: a shortcut of the program, not of a widget."""
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QAbstractSpinBox
        from thzdaq_gui.navigator import FIND_KEY

        key = FIND_KEY.toString(QKeySequence.NativeText)
        assert key in window.quickFind.action.text()
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        window.show_dock("device:power_meter_1")  # floating: a window of its own
        meter = window.docks["device:power_meter_1"]
        assert meter.isFloating()
        for field in (
            window.runBar.controls.comment,
            box.findChildren(QAbstractSpinBox)[0],
            meter.widget().findChildren(QAbstractSpinBox)[0],
        ):
            window.quickFind.hide()
            field.window().activateWindow()
            field.setFocus()
            app.processEvents()
            # Through the window, as the system gives a key: shortcuts first
            QTest.keyClick(field.window().windowHandle(), Qt.Key_K, Qt.ControlModifier)
            assert window.quickFind.isVisible(), field
        window.quickFind.hide()

    def test_custom_graph_rename_delete_and_keep(self, window, session, monkeypatch):
        from thzdaq_gui.graphs import Axis
        from thzdaq_gui.main_window import MainWindow

        hub = window.hub
        graph = hub.new_graph("Mine")
        dock = window.docks["graph:custom1"]
        window.graphs.show(graph)
        # Joins the graphs on screen instead of opening anywhere
        assert dock.dockAreaWidget() is window.docks["graph:I-V"].dockAreaWidget()
        assert dock.isCurrentTab()
        hub.rename(graph, "Mine 2")
        graph.set_axes(Axis("Voltage"), Axis("Current"))
        hub.custom_changed.emit()
        assert hub.graphs["Mine 2"] is graph and "Mine" not in hub.graphs
        assert dock.windowTitle() == "Mine 2"
        assert window.docks.entries["graph:custom1"].title == "Mine 2"
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

    def test_a_graph_is_built_when_shown_or_fed(self, window):
        from thzdaq_gui.graph_docks import DEFAULT_GRAPHS

        hub = window.hub
        assert set(hub.graphs) == set(DEFAULT_GRAPHS)  # those on screen
        body = window.docks["graph:Tn-V"].widget()
        assert not body.built and "graph:Tn-V" in window.docks.entries  # listed
        window.show_dock("graph:Tn-V")
        assert body.attached and body.content() is hub.graphs["Tn-V"]
        graph = hub.graph("P-t")  # for a value of a monitor: its dock holds it
        body = window.docks["graph:P-t"].widget()
        assert body.built and not body.attached
        window.show_dock("graph:P-t")
        assert body.attached and body.content() is graph

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

    def test_device_docks_follow_the_setup(
        self, window, session, profile, monkeypatch, wait
    ):
        setup = window.setupWidget

        def fill(dialog_self):
            dialog_self.kind.setCurrentIndex(dialog_self.kind.findData("sis_bias"))
            dialog_self.channel.setCurrentIndex(dialog_self.channel.findData("DEV1"))
            dialog_self.title.setText("SIS b2d2")
            dialog_self.accept_values()  # Save
            return dialog_self.result()

        monkeypatch.setattr(DeviceDialog, "exec", fill)
        setup.add_device("sis_block_1")
        # The lab tells the profile changed; the docks and Setup follow
        wait(lambda: "device:sis_bias_3" in window.docks)
        saved = load_station(profile).instruments["sis_block_1"].devices["sis_bias_3"]
        assert (saved.kind, saved.channel, saved.title) == (
            "sis_bias",
            "DEV1",
            "SIS b2d2",
        )
        assert "sis b2d2" in setup.cards["sis_block_1"].search_text

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        setup.delete_device("sis_block_1", "sis_bias_3")
        wait(lambda: "device:sis_bias_3" not in window.docks)
        setup.delete_instrument("power_supply_2")
        wait(lambda: "device:power_supply_2" not in window.docks)
        assert "device:yig_power_1" not in window.docks
        assert "power_supply_2" not in load_station(profile).instruments

    def test_add_instrument_dialog(self, window, session, profile, monkeypatch, wait):
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
        )

        def fill(dialog_self):
            dialog_self.driver.setCurrentIndex(dialog_self.driver.findData("rs.nrx"))
            dialog_self.title.setText("Second NRX")
            dialog_self.connection.host.setText("")
            dialog_self.accept_values()  # refused: a socket needs a host
            assert dialog_self.result() != QDialog.Accepted and warnings
            dialog_self.connection.host.setText("10.0.0.7")
            dialog_self.accept_values()
            return dialog_self.result()

        monkeypatch.setattr(InstrumentDialog, "exec", fill)
        window.setupWidget.add_instrument()
        spec = load_station(profile).instruments["power_meter_2"]
        assert spec.title == "Second NRX" and spec.connection.host == "10.0.0.7"
        assert spec.connection.port == 5025  # from the recommended connection
        assert "host" in warnings[0]
        wait(lambda: "device:power_meter_2" in window.docks)

    def test_a_generic_instrument_is_added_by_its_name_and_gets_a_console(
        self, window, profile, monkeypatch, wait
    ):
        from thzdaq_gui.docks.setup import GENERIC_RAW, OFFERS

        setup = window.setupWidget
        menu = [action.text() for action in setup.btnAdd.menu().actions()]
        assert menu == [offer.title for offer in OFFERS]
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
        )

        def fill(dialog_self):
            keys = [
                dialog_self.driver.itemData(i)
                for i in range(dialog_self.driver.count())
            ]
            assert keys == ["generic.scpi"]  # no drivers of models here
            assert dialog_self.ident.text() == "generic_1"
            dialog_self.ident.setText("power_meter_1")
            dialog_self.accept_values()  # taken
            assert "power_meter_1 is taken" in warnings[-1]
            dialog_self.ident.setText("gauge_1")
            dialog_self.title.setText("Vacuum gauge")
            kind = dialog_self.connection.kind
            kind.setCurrentIndex(kind.findData("socket"))
            dialog_self.connection.host.setText("169.254.0.50")
            dialog_self.connection.port.setValue(5025)
            dialog_self.accept_values()
            return dialog_self.result()

        monkeypatch.setattr(InstrumentDialog, "exec", fill)
        setup.add_instrument(GENERIC_RAW)
        spec = load_station(profile).instruments["gauge_1"]
        assert (spec.driver, spec.title, spec.connection.port) == (
            "generic.scpi", "Vacuum gauge", 5025,
        )  # fmt: skip
        wait(lambda: "device:gauge_1" in window.docks)  # its raw console
        assert "device:sis_block_1" not in window.docks  # its devices have it

    def test_connection_editor_shows_fields_of_the_kind(self, app, session):
        dialog = InstrumentDialog(session, lambda *a: None, "signal_generator_1")
        editor = dialog.connection
        assert editor.kind.currentData() == PROLOGIX
        assert editor.gpib.value() == 19 and not editor.gpib.isHidden()
        assert editor.serial_port.isHidden()
        assert not dialog.driver.isEnabled()
        assert dialog.instrument()["connection"]["gpib"] == 19

    def test_driver_list_has_no_simulators_or_pfeiffer(self, app, session):
        dialog = InstrumentDialog(session, lambda *a: None)
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

    def test_editing_keeps_a_driver_no_longer_offered(self, app, session, monkeypatch):
        from thzdaq_api.station import StationProfile

        gauge = {
            "driver": "pfeiffer.gauge",
            "title": "G",
            "connection": {"kind": "serial", "serial_port": "COM3"},
        }
        profile = StationProfile("bench", None, True, {"instruments": {"gauge": gauge}})
        monkeypatch.setattr(session, "profile", lambda: profile)
        dialog = InstrumentDialog(session, lambda *a: None, "gauge")
        assert dialog.driver_key() == "pfeiffer.gauge"
        assert dialog.instrument()["driver"] == "pfeiffer.gauge"
        assert dialog.instrument()["connection"]["serial_port"] == "COM3"

    def test_connect_reports_identity(self, window, wait):
        window.setupWidget.connect_instrument("sis_block_1")
        card = window.setupWidget.cards["sis_block_1"]
        wait(lambda: card.status.text().startswith("OK"))
        assert "SimSisBlock" in card.status.text()

    def test_safety_is_edited_and_checked_by_the_lab(
        self, window, session, profile, monkeypatch
    ):
        from PySide6.QtWidgets import QTableWidgetItem
        from thzdaq_api.devices import DescribeDevice
        from thzdaq_gui.docks.safety import SafetyDialog

        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
        )

        def fill(dialog):
            limits = dialog.limits
            row = limits.add_row("sis_bias_1", "voltage_set")
            assert limits.item(row, 2).text() == "mV"  # typed as the dock shows it
            limits.setItem(row, 3, QTableWidgetItem("8"))  # min
            limits.setItem(row, 4, QTableWidgetItem("-8"))  # max
            dialog.accept_values()  # refused by the lab: the dialog stays
            assert dialog.result() != QDialog.Accepted
            assert "min is above max" in warnings[-1]
            limits.item(row, 3).setText("-8")
            limits.item(row, 4).setText("8")
            limits.setItem(row, 7, QTableWidgetItem("0.5"))  # step
            state = dialog.safe_state
            row = state.add_row("sis_bias_1", "voltage_set")
            state.item(row, state.VALUE).setText("0")
            row = state.add_row("signal_generator_1", "output")
            state.cellWidget(row, state.VALUE).setCurrentText("Off")
            dialog.protection.setChecked(True)
            dialog.accept_values()
            return dialog.result()

        monkeypatch.setattr(SafetyDialog, "exec", fill)
        window.setupWidget.edit_safety()
        safety = load_station(profile).safety
        limit = safety.limits["sis_bias_1"]["voltage_set"]
        assert (limit.minimum, limit.maximum) == (pytest.approx(-8e-3), 8e-3)
        assert limit.step == pytest.approx(5e-4) and limit.rate is None
        assert safety.safe_state == {
            "sis_bias_1": {"voltage_set": 0.0},
            "signal_generator_1": {"output": False},
        }
        assert safety.hardware_protection
        # The bench takes them at once
        described = session.call(DescribeDevice(ref="sis_bias_1")).quantities
        voltage = next(q for q in described if q.key == "voltage_set")
        assert voltage.maximum == pytest.approx(8e-3)
        # Shown again as they were saved
        dialog = SafetyDialog(session)
        assert dialog.limits.text(0, 4) == "8" and dialog.limits.text(0, 7) == "0.5"
        assert dialog.safe_state.rowCount() == 2 and dialog.protection.isChecked()


class TestDeviceDocks:
    def test_quantity_panel_reads_and_sets(
        self, window, session, wait, monkeypatch, bench
    ):
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

        assert (
            float(settings().value(setpoint_key("sis_bias_1", "voltage_set"))) == 2.5e-3
        )
        # Active is the opposite of the block's short: off shorts the output.
        # It may harm a biased junction, so a person is asked first
        asked = []
        answer = [QMessageBox.No]
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or answer[0]
        )
        active = next(q for q in panel.quantities if q.key == "active")
        channel = bench.station.instrument("sis_block_1").channel("DEV4")
        shorted = channel.get_short()
        panel.write(active, shorted)
        assert asked and active.danger in asked[0]
        assert channel.get_short() == shorted  # no: nothing is written
        answer[0] = QMessageBox.Yes
        panel.write(active, True)
        wait(lambda: panel.toggles["active"].isChecked())
        assert not channel.get_short()
        panel.write(active, False)
        wait(lambda: not panel.toggles["active"].isChecked())
        assert channel.get_short()

    def test_generator_configuration_from_the_profile(
        self, window, session, profile, wait, bench
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
        generator = bench.station.instrument("signal_generator_1")
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

    def test_fields_take_values_in_the_chosen_prefix(
        self, window, session, wait, bench
    ):
        main = window.docks["device:signal_generator_1"].widget().panels[0]
        field = main.fields["frequency"]
        assert field.prefix.prefix() == "G" and "×10⁹" in field.prefix.currentText()
        field.spin.setValue(223.5)
        assert field.pending and field.value() == 223.5e9
        field.prefix.setCurrentIndex(field.prefix.findData("M"))
        assert field.spin.value() == 223500.0 and field.value() == 223.5e9
        field.apply_requested.emit()  # Enter
        generator = bench.station.instrument("signal_generator_1")
        wait(lambda: generator.get_frequency() == 223.5e9)
        wait(lambda: not field.pending)
        sis = window.docks["device:sis_bias_1"].widget().panels[0]
        assert sis.fields["voltage_set"].prefix.prefix() == "m"
        assert sis.displays["current"].prefix() == "µ"

    def test_chopper_dock(self, window, session, wait, bench):
        from thzdaq_gui.docks.devices import START_ROTATION, STOP, TO_HOT, ChopperGroup

        widget = window.docks["device:chopper_1"].widget()
        main = widget.panels[0]
        assert [q.key for q in main.quantities] == ["load_state", "running"]
        group = widget.findChildren(ChopperGroup)[0]
        chopper = bench.station.instrument("chopper_1")
        group.call(TO_HOT)
        wait(lambda: main.values["load_state"].text() == "hot")
        group.arguments[START_ROTATION].editors["frequency"].set(5.5)
        group.call(START_ROTATION)
        wait(lambda: chopper.running and main.toggles == {} and
             main.values["running"].text() == "ON")  # fmt: skip
        assert chopper.frequency == 5.5
        group.call(STOP)
        wait(lambda: not chopper.running)

    def test_spectrum_dock_applies_and_reads(self, window, session, wait, bench):
        from thzdaq_api.devices import POWER_DBM
        from thzdaq_gui.docks.devices import CONFIGURE, TraceGroup

        group = (
            window.docks["device:spectrum_analyzer_1"]
            .widget()
            .findChildren(TraceGroup)[0]
        )
        assert group.title() == "Spectrum analyzer"
        analyzer = bench.station.instrument("spectrum_analyzer_1")
        sweep = group.arguments[CONFIGURE].editors
        sweep["center"].set(6e9)
        sweep["span"].set(2e9)
        group.call(CONFIGURE)
        wait(lambda: (analyzer.center, analyzer.span) == (6e9, 2e9))
        group.read()
        wait(lambda: group.curve.getData()[0] is not None and not group.pending)
        assert min(group.curve.getData()[0]) == pytest.approx(5e9)
        assert group.graph.getAxis("left").labelText == POWER_DBM

    def test_coil_monitor_shows_the_current(self, window, session, wait, bench):
        """The coil had only its setpoint field: Monitor showed nothing new."""
        panel = window.docks["device:sis_coil_1"].widget().panels[0]
        coil = bench.station.device("sis_coil_1")
        coil.set_current(2.5e-3)  # e.g. a demagnetization left it there
        label = panel.values["coil_current"]
        assert label.property("role") == "value"  # orange, as the bias values
        assert panel.displays["coil_current"].prefix() == "m"
        panel.interval.setValue(0.1)
        panel.monitor.setChecked(True)
        wait(lambda: label.text() == "2.5 mA")
        coil.set_current(1e-3)
        wait(lambda: label.text() == "1 mA")
        # The lab polls the coil for the dock; Monitor off ends the subscription
        from thzdaq_api.daemon import GetDaemonStatus

        def polls():
            return [(p.ref, p.interval) for p in session.call(GetDaemonStatus()).polls]

        assert polls() == [("sis_coil_1", pytest.approx(0.1))]
        panel.monitor.setChecked(False)
        wait(lambda: polls() == [])

    def test_generator_monitor_shows_what_it_holds(self, window, wait, bench):
        """Frequency, power and output were fields only: Monitor showed nothing."""
        panel = window.docks["device:signal_generator_2"].widget().panels[0]
        generator = bench.station.instrument("signal_generator_2")
        held = {
            key: panel.values[key] for key in ("frequency", "power_level", "output")
        }
        assert all(label.property("role") == "value" for label in held.values())
        panel.interval.setValue(0.1)
        panel.monitor.setChecked(True)
        generator.set_frequency(223e9)  # on the front panel, or by a script
        generator.set_power(-10.0)
        generator.set_output(True)
        wait(lambda: (held["frequency"].text(), held["power_level"].text(),
                      held["output"].text()) == ("223 GHz", "-10 dBm", "ON"))  # fmt: skip
        panel.monitor.setChecked(False)

    def test_grid_dock_shows_its_angle_and_sets_its_zero(self, window, wait, bench):
        from thzdaq_gui.docks.devices import ActionsGroup

        widget = window.docks["device:grid_1"].widget()
        panel = widget.panels[0]
        grid = bench.station.instrument("grid_1")
        panel.fields["angle"].set_value(30.0, pending=True)
        panel.apply(panel.by_key["angle"])
        wait(lambda: panel.values["angle"].text() == "30 deg")
        group = widget.findChildren(ActionsGroup)[0]
        group.call("zero")
        wait(lambda: panel.values["angle"].text() == "0 deg")
        assert grid.position == 30.0  # nothing moved
        grid.restore_state({"angle": 0.0, "moving_to": 45.0})  # left moving
        panel.read()
        wait(lambda: not panel.problem.isHidden())
        assert "set its zero" in panel.problem.text()
        assert panel.values["angle"].text() == "--"
        group.call("zero")
        wait(lambda: panel.problem.isHidden() and
             panel.values["angle"].text() == "0 deg")  # fmt: skip

    def test_yig_monitor_shows_its_frequency(self, window, wait, bench):
        widget = window.docks["device:yig_filter_1"].widget()
        panel = next(p for p in widget.panels if "frequency" in p.by_key)
        channel = bench.station.instrument("yig_filter_1").channel(
            panel.ref.split(":")[-1]
        )
        channel.tune(6e9)
        panel.interval.setValue(0.1)
        panel.monitor.setChecked(True)
        wait(lambda: panel.values["frequency"].text().startswith("5.99")
             or panel.values["frequency"].text().startswith("6"))  # fmt: skip
        panel.monitor.setChecked(False)

    def test_a_supply_shows_what_it_measures_not_its_setpoints(self, window):
        panel = window.docks["device:power_supply_1"].widget().panels[1]
        assert "voltage" in panel.values and "voltage_set" not in panel.values

    def test_raw_commands_from_a_device_dock(self, window, wait, monkeypatch):
        from thzdaq_gui.docks.raw import RawConsole

        widget = window.docks["device:sis_bias_1"].widget()
        (console,) = widget.findChildren(RawConsole)  # to its block, sis_block_1
        assert not window.docks["device:chopper_1"].widget().findChildren(RawConsole)
        console.line.setText("*IDN?")
        console.send()
        wait(lambda: "< THZDAQ,SimSisBlock,0,1.0" in console.log.toPlainText())
        # A write is confirmed first: no sends nothing
        asked = []
        answer = [QMessageBox.No]
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or answer[0]
        )
        console.line.setText("DEV4:OFF")
        console.send()
        assert asked and "do not check a raw command" in asked[0]
        assert (
            console.line.text() == "DEV4:OFF"
            and "> DEV4" not in console.log.toPlainText()
        )
        # Sent: the dock knows nothing of the bias until the lab read it again
        panel = widget.panels[0]
        panel.read()
        wait(lambda: panel.values["voltage"].text() != "--")
        forgotten = []
        panel.model.unknown.connect(
            lambda: forgotten.append(panel.values["voltage"].text())
        )
        answer[0] = QMessageBox.Yes
        console.send()
        wait(lambda: "sent; read again: " in console.log.toPlainText())
        wait(lambda: forgotten and panel.values["voltage"].text() != "--")
        assert forgotten == ["--"]
        console.recall(1)
        assert console.line.text() == "DEV4:OFF"

    def test_device_docks_use_their_instrument_queue(self, window):
        sis = window.docks["device:sis_bias_1"].widget().panels[0]
        meter = window.docks["device:power_meter_1"].widget().panels[0]
        supply = window.docks["device:power_supply_1"].widget().panels
        assert (sis.model.lane, meter.model.lane) == ("sis_block_1", "power_meter_1")
        assert {p.model.lane for p in supply} == {"power_supply_1"}  # channels too

    def test_instrument_dock_has_its_channels(self, window):
        widget = window.docks["device:power_supply_1"].widget()
        assert [p.ref for p in widget.panels] == [
            "power_supply_1", "power_supply_1:1", "power_supply_1:2", "power_supply_1:3",
        ]  # fmt: skip

    def test_monitor_plots_to_time_graphs(self, window, wait):
        panel = window.docks["device:power_meter_1"].widget().panels[0]
        panel.interval.setValue(0.1)
        shown = []
        window.hub.run_requested.connect(
            lambda widgets: shown.append([w.title for w in widgets])
        )
        panel.plot.setChecked(True)
        panel.monitor.setChecked(True)
        graph = window.hub.graph("P-t")
        wait(lambda: graph.items and len(next(iter(graph.points.values()))) >= 2)
        panel.monitor.setChecked(False)
        key = ("monitor", "power_meter_1", "power")
        assert graph.curve_label(key) == "R&S NRX Power"
        assert shown == [["P-t"]]  # once, not on every reading

    def test_a_sis_bias_monitor_shows_both_its_graphs(self, window, wait, app):
        """I-t and V-t come on screen when the monitor starts, each in front
        of a group of its own, so both are seen at once; again at the next
        start."""
        panel = window.docks["device:sis_bias_1"].widget().panels[0]
        panel.interval.setValue(0.1)
        for title in ("I-t", "V-t"):
            window.docks[f"graph:{title}"].toggleView(False)
        shown = []
        window.hub.run_requested.connect(
            lambda widgets: shown.append(sorted(w.title for w in widgets))
        )
        panel.plot.setChecked(True)
        panel.monitor.setChecked(True)
        wait(lambda: shown)
        panel.monitor.setChecked(False)
        app.processEvents()
        assert shown == [["I-t", "V-t"]]
        current, voltage = (window.docks[f"graph:{t}"] for t in ("I-t", "V-t"))
        assert not current.isClosed() and not voltage.isClosed()
        assert current.isCurrentTab() and voltage.isCurrentTab()
        assert current.dockAreaWidget() is not voltage.dockAreaWidget()
        panel.monitor.setChecked(True)
        wait(lambda: len(shown) == 2)
        panel.monitor.setChecked(False)

    def test_sis_bias_offsets_and_calibration(
        self, window, session, profile, wait, monkeypatch, bench
    ):
        from thzdaq_gui.docks.devices import CalibrationGroup, SettingsGroup

        widget = window.docks["device:sis_bias_2"].widget()

        group = widget.findChildren(SettingsGroup)[0]
        assert list(group.fields) == ["offset_voltage", "offset_current"]
        field = group.fields["offset_voltage"]
        assert field.prefix.symbol() == "µV"  # same field as the rest of the dock
        field.set_value(1e-4, pending=True)
        assert field.spin.value() == pytest.approx(100.0)
        field.apply_requested.emit()  # Enter saves
        assert not field.pending
        assert load_station(profile).instruments["sis_block_1"].devices[
            "sis_bias_2"
        ].settings["offset_voltage"] == pytest.approx(1e-4)
        # The device uses them; the dock is not rebuilt for its own values
        assert bench.station.device("sis_bias_2").offset_voltage == pytest.approx(1e-4)
        assert window.docks["device:sis_bias_2"].widget() is widget

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        shown = []
        monkeypatch.setattr(
            QMessageBox, "information", lambda *a, **k: shown.append(a[2])
        )
        calibration = widget.findChildren(CalibrationGroup)[0]
        calibration.write_calibration()
        wait(lambda: shown)
        channel = bench.station.instrument("sis_block_1").channel("DEV2")
        assert channel.calibration["VoltageStep"] == pytest.approx(1e-5)

        # Edited coefficients: the lab checks them, a refusal stays in the dialog
        from thzdaq_gui.docks.devices import CalibrationDialog

        def edit(dialog_self):
            data = json.loads(dialog_self.editor.toPlainText())
            data["VoltageStep"] = "1e-5 *"
            dialog_self.editor.setPlainText(json.dumps(data))
            dialog_self.check()
            assert "VoltageStep" in dialog_self.problem.text()
            data["VoltageStep"] = "2e-5 / 2"
            dialog_self.editor.setPlainText(json.dumps(data))
            dialog_self.check()
            return dialog_self.result()

        monkeypatch.setattr(CalibrationDialog, "exec", edit)
        calibration.edit_calibration()
        device = load_station(profile).instruments["sis_block_1"].devices["sis_bias_2"]
        assert device.metadata["calibration_coefficients"]["VoltageStep"] == "2e-5 / 2"

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
        box.form.set_values({**FAST_IV, "voltage": sweep(0, 7e-3, 141)})
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        wait(lambda: finished)
        bar = window.hub.graph("I-V").analysis
        # The curve of the run is offered (the list stayed empty before)
        assert bar.curve.count() == 1
        assert bar.curve.currentData()[0] == finished[0].id
        result = bar.analyze()
        assert result is not None and result.rn.resistance > 0, bar.label.text()
        window.hub.graph("I-V").clear()
        assert bar.curve.count() == 0 and not bar.overlay.items


class TestMeasureAndData:
    def test_saved_parameters_survive_a_dropped_one(self, window, session):
        from thzdaq_api.procedures import TWO_SB_LO_RF_BALANCE
        from thzdaq_gui.docks.measure import ProcedureBox
        from thzdaq_gui.settings import settings

        saved = {"bias_delay": 0.7, "silence_old": False}  # no longer a parameter
        key = procedure_key(TWO_SB_LO_RF_BALANCE)
        settings().setValue(key, json.dumps({"parameters": saved, "devices": {}}))
        try:
            box = ProcedureBox(session, window.hub, TWO_SB_LO_RF_BALANCE)
            assert box.form.values()["bias_delay"] == pytest.approx(0.7)
        finally:
            settings().remove(key)

    def test_saved_parameters_of_an_old_name_are_taken(self, window, session):
        from thzdaq_gui.docks.measure import ProcedureBox
        from thzdaq_gui.settings import settings

        old = procedure_key(
            "sis.current_vs_voltage"
        )  # kept before the procedure was renamed
        current = procedure_key(CURRENT_VS_VOLTAGE)
        kept = settings().value(current)
        settings().remove(current)  # nothing kept under the name it has now
        saved = {"parameters": {"settle_time": 0.25}, "devices": {}}
        settings().setValue(old, json.dumps(saved))
        try:
            box = ProcedureBox(session, window.hub, CURRENT_VS_VOLTAGE)
            assert box.form.values()["settle_time"] == pytest.approx(0.25)
        finally:
            settings().remove(old)
            if kept:
                settings().setValue(current, kept)

    def test_slots_and_fields_follow_the_parameters(self, window):
        box = window.docks["measure:sis.noise_temperature_vs_voltage"].widget().box
        assert box.devices.combos["load"].currentData()
        assert "Load" in box.devices_box.summary.text()
        assert box.form.shown("t_hot") and not box.form.shown("angle")
        box.form.editors["hot_cold"].widget.setChecked(False)
        assert "load" not in box.devices.combos
        assert not box.form.shown("t_hot") and not box.form.shown("load_delay")
        box.form.editors["use_grid"].widget.setChecked(True)
        assert "grid" in box.devices.combos and box.form.shown("angle")

    def test_invalid_parameters_are_named_before_a_start(self, window, monkeypatch):
        from thzdaq_gui.wording import INVALID_PARAMETERS

        box = window.docks["measure:two_sb.if_balance"].widget().box
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: warnings.append(a[1:3])
        )
        box.form.editors["sis1_voltages"].widget.setText("")
        box.start()
        ((title, text),) = warnings
        assert title == INVALID_PARAMETERS and "SIS1 voltages" in text
        assert not box.runner.running and not box.status().running

    def test_measurement_dock_flow(self, window, session, wait, tmp_path):
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        box.form.set_values(FAST_IV)
        box.devices.combos["bias"].setCurrentIndex(
            box.devices.combos["bias"].findData("sis_bias_2")
        )
        QTest.keyClicks(box.controls.comment, "smoke test")
        finished = []
        box.runner.finished.connect(finished.append)
        box.controls.btnStart.click()
        wait(lambda: finished and box.controls.btnStart.isEnabled())
        measurement = finished[0]
        assert measurement.status == COMPLETED and measurement.comment == "smoke test"
        assert measurement.devices["bias"].ref == "sis_bias_2"
        graph = window.hub.graph("I-V")
        (key,) = graph.items
        assert graph.curve_label(key).startswith("#1 SIS2")
        model = session.measurements
        assert model.rowCount() == 1 and model.data(model.index(0, 5)) == COMPLETED
        saved = read_measurement(measurement.metadata["path"])
        assert saved.tables["iv"].data["voltage"][0] == 0.0
        # Comments edited in the table go to the file (the daemon writes it)
        model.setData(model.index(0, 2), "edited")
        wait(lambda: read_measurement(measurement.metadata["path"]).comment == "edited")
        # The next start remembers the devices and parameters
        again = type(box)(session, window.hub, box.procedure)
        assert again.devices.mapping()["bias"] == "sis_bias_2"
        assert again.form.values()["voltage"] == FAST_IV["voltage"]

    def test_data_dock_opens_plots_and_exports(
        self, window, session, wait, tmp_path, monkeypatch
    ):
        from thzdaq_api.measurement_file import Measurement
        from thzdaq_core.adapters.json_store import MeasurementStore

        measurement = Measurement(
            "sis.current_vs_voltage",
            title="SIS I-V curve",
            started="2026-10-29T12:00:00.000",
        )
        for v in (1e-3, 2e-3):
            measurement.append("iv", {"voltage": v, "current": v / 20})
        path = MeasurementStore(tmp_path / "other").save(measurement)
        data = window.dataWidget
        monkeypatch.setattr(
            "thzdaq_gui.folders.QFileDialog.getOpenFileNames",
            lambda *a, **k: ([str(path)], ""),
        )
        data.open_files()
        assert session.measurements.rowCount() == 1
        assert len(window.hub.graph("I-V").items) == 1
        data.table.selectRow(0)
        csv_path = tmp_path / "iv.csv"
        monkeypatch.setattr(
            "thzdaq_gui.folders.QFileDialog.getSaveFileName",
            lambda *a, **k: (str(csv_path), ""),
        )
        data.export()
        assert (
            csv_path.read_text(encoding="utf-8")
            .splitlines()[0]
            .startswith('"Voltage, V"')
        )

    def test_a_file_of_an_old_name_shows_and_draws_as_now(
        self, window, session, tmp_path, monkeypatch
    ):
        from thzdaq_api.measurement_file import Measurement
        from thzdaq_core.adapters.json_store import MeasurementStore

        # Measured before the renaming; its file keeps no plots
        old = Measurement(
            "sis.current_vs_coil_current",
            title="SIS I-CL curve",
            started="2026-10-29T12:00:00.000",
        )
        for current in (1e-3, 2e-3):
            old.append("cl", {"coil_current": current, "current": 1e-6})
        path = MeasurementStore(tmp_path / "old").save(old)
        monkeypatch.setattr(
            "thzdaq_gui.folders.QFileDialog.getOpenFileNames",
            lambda *a, **k: ([str(path)], ""),
        )
        window.dataWidget.open_files()
        model = session.measurements
        index = model.index(0, 1)
        assert model.data(index) == "SIS Josephson suppression"
        assert "SIS I-CL curve (sis.current_vs_coil_current)" in model.data(
            index, Qt.ToolTipRole
        )
        assert len(window.hub.graph("I-CL").items) == 1

    def test_file_dialogs_start_where_the_last_file_went(
        self, window, session, tmp_path, monkeypatch
    ):
        import shutil
        from pathlib import Path

        from thzdaq_api.measurement_file import Measurement
        from thzdaq_gui.folders import MEASUREMENTS, Folders
        from thzdaq_gui.settings import settings

        settings().remove("folders")
        measurement = Measurement("sis.current_vs_voltage", title="SIS I-V curve")
        measurement.append("iv", {"voltage": 1e-3, "current": 5e-5})
        session.measurements.add(measurement)
        window.dataWidget.table.selectRow(0)
        results = tmp_path / "results"
        starts = []

        def save(parent, title, start, filters):
            starts.append(Path(start).parent.resolve())
            return str(results / Path(start).name), ""

        monkeypatch.setattr("thzdaq_gui.folders.QFileDialog.getSaveFileName", save)
        # Nothing chosen yet: the data folder of the session, not the program's
        window.dataWidget.save_as()
        assert starts[0] == session.data_root.resolve()
        assert (results / f"{measurement.id}_sis_current_vs_voltage.json").exists()
        # Then where the last file went, also after a restart
        window.dataWidget.export()
        assert starts[1] == results.resolve()
        assert (results / f"{measurement.id}_iv.csv").exists()
        later = Folders({MEASUREMENTS: lambda: tmp_path / "data"})
        assert later.folder(MEASUREMENTS) == results.resolve()
        # A folder that is gone (a removed USB stick): the default again
        shutil.rmtree(results)
        assert later.folder(MEASUREMENTS) == tmp_path / "data"

    def test_monitor_dock_watches_ticked_values(self, window, session, wait):
        box = window.docks["measure:monitor.values_vs_time"].widget().box
        tree = box.devices
        tree.set_device("power_meter_1", True)
        tree.set_device("sis_bias_1", True)
        assert sorted(tree.entries()) == [
            "power_meter_1/power",
            "sis_bias_1/current",
            "sis_bias_1/voltage",
        ]
        # Expand the SIS bias and keep only the voltage
        bias = next(
            i for i in tree.device_items() if i.data(0, Qt.UserRole) == "sis_bias_1"
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
        shown = []
        window.hub.run_requested.connect(
            lambda widgets: shown.append([w.title for w in widgets])
        )
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        # At Start, before any reading: the graphs of the units chosen
        assert shown == [["P-t", "V-t"]]
        wait(lambda: finished)
        samples = finished[0].records("samples")
        assert {(s["device"], s["key"]) for s in samples} == {
            ("R&S NRX", "power"),
            ("SIS1", "voltage"),
        }
        assert window.hub.graph("P-t").items and window.hub.graph("V-t").items
        assert not window.hub.graph("p-t").items
        assert shown == [["P-t", "V-t"]]  # nothing unexpected got data
        # Both in front, each in its own tab group
        v_t, p_t = window.docks["graph:V-t"], window.docks["graph:P-t"]
        assert p_t.isCurrentTab() and v_t.isCurrentTab()
        assert v_t.dockAreaWidget() is not p_t.dockAreaWidget()
        assert box.window == 60
        assert isinstance(finished[0].id, int)
        # The choice is remembered
        box.refresh_devices()
        assert sorted(tree.entries()) == ["power_meter_1/power", "sis_bias_1/voltage"]


class TestLayout:
    def test_a_restored_layout_keeps_widths_and_holds_only_open_contents(
        self, window, session, app
    ):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QSplitter
        from thzdaq_gui.docks.body import DockBody
        from thzdaq_gui.main_window import MainWindow

        def settle():
            for _ in range(5):
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        def widths(of):
            return sorted(
                str(s.sizes())
                for s in of.dock_manager.findChildren(QSplitter)
                if s.isVisible()
            )

        window.resize(1500, 900)
        settle()
        for splitter in window.dock_manager.findChildren(QSplitter):
            if splitter.isVisible() and splitter.count() == 2:
                total = sum(splitter.sizes())
                splitter.setSizes([total // 4, total - total // 4])
        window.show_dock("measure:monitor.values_vs_time")  # floating
        settle()
        expected = widths(window)
        window.save_state()
        again = MainWindow(session, window.settings.fileName(), check_updates=False)
        again.confirm_exit = False
        again.resize(window.size())  # the offscreen screen is smaller
        again.show()
        settle()
        assert widths(again) == expected
        assert again.docks["measure:monitor.values_vs_time"].isFloating()
        # Closed device and measurement docks carry no content
        for name, dock in again.docks.items():
            body = dock.widget()
            if isinstance(body, DockBody):
                assert body.attached == (not dock.isClosed()), name
        # Not placed in the saved layout: still opens floating
        again.show_dock("device:power_supply_1")
        assert again.docks["device:power_supply_1"].isFloating()
        again.close()

    def test_old_settings_give_the_default_layout(self, window, session):
        """The layout and keys of Lite and Pro: the layout is refused (another
        version) and the default made, nothing fails."""
        from PySide6.QtCore import QSettings
        from thzdaq_gui.main_window import MainWindow

        window.save_state()
        settings = QSettings(window.settings.fileName(), QSettings.IniFormat)
        old = window.dock_manager.saveState(3)  # the version of Lite and Pro
        settings.setValue(LAYOUT, old)
        settings.setValue("window/docks_lite", old)
        settings.setValue("ui/mode", "pro")
        settings.setValue("perspective", "Default")
        settings.sync()
        again = MainWindow(session, settings.fileName(), check_updates=False)
        again.confirm_exit = False
        again.show()
        chosen = again.docks["measure:sis.current_vs_voltage"]
        assert not chosen.isClosed() and not chosen.isFloating()
        assert not again.docks["graph:I-V"].isClosed()
        assert again.docks["processes"].isAutoHide()
        again.close()

    def test_settings_keep_the_station_path(self, window, session, tmp_path):
        window.on_station_changed()
        assert window.settings.value(STATION_PATH) == session.profile().path

    def test_the_window_follows_a_profile_another_client_loads(
        self, window, session, profile, wait
    ):
        """A CLI (another client of the same lab) loads a profile: the window
        rebuilds its docks for it and remembers it."""
        import shutil

        from thzdaq_api.station import LoadStation

        other = profile.with_name("other.yaml")
        shutil.copy(profile, other)
        text = other.read_text(encoding="utf-8")
        other.write_text(text.replace("name: 2sb", "name: other"), encoding="utf-8")
        cli = session.lab_of(True)
        cli.origin = "cli"
        cli.call(LoadStation(path=str(other)))
        wait(lambda: window.stationLabel.text().startswith("Station: other"))
        assert window.settings.value(STATION_PATH) == str(other)
        assert "device:sis_bias_1" in window.docks


def test_measurement_json_is_plain(tmp_path):
    from thzdaq_api.measurement_file import Measurement
    from thzdaq_core.adapters.json_store import MeasurementStore

    measurement = Measurement("demo", started="2026-10-29T12:00:00.000")
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

        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        box.form.set_values(FAST_IV)
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()
        wait(lambda: finished)
        exit_answer["store"], exit_answer["dump"] = False, True
        assert window.close()
        (dump,) = (tmp_path / "data" / "dumps").glob("dump_*.json")
        data = json.loads(dump.read_text(encoding="utf-8"))
        assert [m["procedure"] for m in data] == ["sis.current_vs_voltage"]
        assert data[0]["tables"]["iv"]["data"]["voltage"][0] == 0.0
        assert window.settings.value(LAYOUT) is None  # layout not stored

    def test_dialog_defaults(self, app):
        from thzdaq_gui.exit_dialog import ExitDialog

        idle = ExitDialog(running=0, measurements=0)
        assert idle.storeState.isChecked() and not idle.dumpData.isEnabled()
        busy = ExitDialog(running=2, measurements=3)
        assert busy.dumpData.isChecked() and "3" in busy.dumpData.text()
        # The daemon stops with the window only when nothing else needs it
        assert idle.stopDaemon.isChecked() and not busy.stopDaemon.isChecked()
        shared = ExitDialog(running=0, measurements=0, others=1)
        assert not shared.stopDaemon.isChecked()
        gone = ExitDialog(running=0, measurements=0, daemon=False)
        assert not gone.stopDaemon.isEnabled() and not gone.stopDaemon.isChecked()

    def test_the_daemon_is_stopped_as_chosen(self, window, exit_answer, monkeypatch):
        from thzdaq_gui.models.daemon import DaemonModel

        stopped = []
        monkeypatch.setattr(
            DaemonModel, "stop_now", lambda self, mode: stopped.append(mode)
        )
        exit_answer["stop"] = False
        window.confirm_exit = True
        assert window.close() and stopped == []

    def test_dialog_offers_the_daemon_left_at_a_switch(self, app):
        from thzdaq_gui.exit_dialog import ExitDialog
        from thzdaq_gui.models.daemon import LeftDaemon

        assert ExitDialog(running=0, measurements=0).stopLeft is None
        idle = ExitDialog(0, 0, left=LeftDaemon(simulate=False, running=0, others=0))
        assert idle.stopLeft.isChecked() and "instruments'" in idle.stopLeft.text()
        busy = ExitDialog(0, 0, left=LeftDaemon(simulate=True, running=1, others=0))
        assert not busy.stopLeft.isChecked() and "simulator's" in busy.stopLeft.text()
        shared = ExitDialog(0, 0, left=LeftDaemon(simulate=False, running=0, others=1))
        assert not shared.stopLeft.isChecked()

    def test_dialog_stops_the_daemons_an_update_replaces(self, app):
        from thzdaq_gui.exit_dialog import ExitDialog
        from thzdaq_gui.models.daemon import LeftDaemon

        left = LeftDaemon(simulate=False, running=1, others=0)
        dialog = ExitDialog(0, 0, others=1, left=left, updating=True)
        for check in (dialog.stopDaemon, dialog.stopLeft):
            assert check.isChecked() and not check.isEnabled()
        gone = ExitDialog(0, 0, daemon=False, updating=True)  # nothing to stop
        assert not gone.stopDaemon.isChecked()

    def test_the_daemon_left_at_a_switch_stops_with_the_window(
        self, window, session, monkeypatch
    ):
        from thzdaq_api.daemon import StopMode
        from thzdaq_gui.models.daemon import DaemonModel

        stopped = []
        for name in ("stop_now", "stop_left"):
            monkeypatch.setattr(
                DaemonModel,
                name,
                lambda self, mode, name=name: stopped.append((name, mode)),
            )
        assert session.left is None
        window.set_simulate(False)  # the simulator's daemon goes on
        assert session.left is not None and not session.simulate
        window.confirm_exit = True
        assert window.close()
        assert stopped == [
            ("stop_now", StopMode.GRACEFUL),
            ("stop_left", StopMode.GRACEFUL),
        ]

    def test_a_left_daemon_that_ended_is_not_offered(self, window, session):
        from thzdaq_api.errors import ErrorCode, LabError

        class Ended:  # its idle timeout ended it
            origin = "gui"

            def call(self, operation):
                raise LabError(ErrorCode.UNREACHABLE, "no daemon")

        session.left = Ended()
        assert window.daemon.ask_left() is None


def test_closed_windows_leave_nothing_alive(app, connect, tmp_path, freed):
    """A closed window is deleted with its docks, graphs and timers, the
    content of a closed dock too (it has no parent); each window of the tests
    stayed alive, and the run grew slower and bigger with every test."""
    from PySide6.QtCore import QTimer
    from thzdaq_gui.main_window import MainWindow
    from thzdaq_gui.session import Session

    def alive():
        freed()
        timers = {t for w in app.topLevelWidgets() for t in w.findChildren(QTimer)}
        return len(app.allWidgets()), len(timers)

    def open_and_close():
        session = Session(connect, tmp_path)
        session.open(True)
        window = MainWindow(
            session, str(tmp_path / "s.ini"), restore_layout=False,
            check_updates=False,
        )  # fmt: skip
        window.show()
        window.docks.open("device:power_meter_1")
        window.docks.toggle("device:power_meter_1")
        assert not window.docks["device:power_meter_1"].widget().attached
        assert window.close()  # shuts the session down
        session.deleteLater()

    before = alive()
    for _ in range(2):
        open_and_close()
        assert alive() == before


def test_a_removed_dock_is_not_built_again(window):
    body = window.docks["device:power_meter_1"].widget()
    window.docks.open("device:power_meter_1")
    window.docks.remove("device:power_meter_1")
    assert not body.built  # deleted, not built again for a last look at its plots


def test_no_stray_windows_flash(app, session, tmp_path):
    """Widgets shown before they have a parent pop up as small windows."""

    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget
    from thzdaq_gui import profile as fmt
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
            session,
            str(tmp_path / "s.ini"),
            restore_layout=False,
            check_updates=False,
        )
        window.show()
        edited = fmt.changed(session.profile().profile)
        sis_block = fmt.instruments(edited)["sis_block_1"]
        fmt.devices(sis_block)["sis_bias_3"] = {"kind": "sis_bias", "channel": "DEV1"}
        session.update_profile(edited)
        app.processEvents()
        # Dock contents detached and attached again (closing, a layout)
        dock = window.docks["device:sis_bias_1"]
        dock.toggleView(False)
        state = window.dock_manager.saveState()
        dock.toggleView(True)
        window.dock_manager.restoreState(state)
        window.docks.sync_bodies()
        app.processEvents()
    finally:
        app.removeEventFilter(spy)
    assert shown == ["MainWindow"]
    window.close()


class TestHangs:
    def test_watchdog_returns_the_dock_to_idle(self, window):
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        box.on_running(True)  # the dock thinks it runs, the thread is gone
        assert not box.controls.btnStart.isEnabled()
        box.check_thread()  # the end signal may still be queued: wait one more look
        assert not box.controls.btnStart.isEnabled()
        box.check_thread()
        assert box.controls.btnStart.isEnabled() and box.status().state == "Idle"

    def test_device_that_does_not_answer_is_named_once(
        self, window, monkeypatch, caplog
    ):
        worker = window.session.calls
        monkeypatch.setattr(type(worker), "current", property(lambda s: "Rigol 1"))
        monkeypatch.setattr(type(worker), "started_at", property(lambda s: 1.0))
        monkeypatch.setattr(worker, "busy_for", lambda: 12.0)
        with caplog.at_level("WARNING"):
            window.hangWatch.check()
            window.hangWatch.check()
        named = [r for r in caplog.records if "Rigol 1 does not answer" in r.message]
        assert len(named) == 1
        assert "Rigol 1" in window.statusBar().currentMessage()

    def test_abort_is_offered_only_while_starting_or_stopping(self, window):
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        box.on_running(True)
        box.update_status(state="Running")
        box.offer_abort()  # a timer of an earlier start or stop
        assert box.controls.btnAbort.isHidden()
        box.stop()
        assert box.stuck.isActive()
        box.on_running(False)
        assert not box.stuck.isActive()

    def test_stop_without_answer_offers_abort(self, window, session, monkeypatch):
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        aborted = []
        monkeypatch.setattr(box.runner, "abort", lambda: aborted.append(True))
        box.on_running(True)
        box.stop()
        abort = box.controls.btnAbort
        assert box.status().state == "Stopping..." and abort.isHidden()
        box.offer_abort()  # STUCK_AFTER_MS later, still running
        assert not abort.isHidden() and "Abort" in box.controls.state.text()
        box.abort()  # the lab breaks the connections of the run's devices
        assert aborted
        box.on_running(False)
        assert abort.isHidden()

    def test_start_while_running_warns(self, window, monkeypatch):
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
        )
        monkeypatch.setattr(box.runner, "running", True)
        box.start()
        assert warnings and "still running" in warnings[0]

    def test_connections_group(self, app, wait, tmp_path):
        from thzdaq_core.adapters.json_store import MeasurementStore
        from thzdaq_api.custom import LIBRARY
        from thzdaq_core.adapters.library import FolderLibrary
        from thzdaq_core.adapters.processes import Processes
        from thzdaq_core.adapters.yaml_profiles import YamlProfiles
        from thzdaq_core.application.assembly import assemble
        from thzdaq_core.application.bench import Bench
        from thzdaq_api.lanes import Lanes
        from thzdaq_core.application.local import LocalControl, LocalLab
        from thzdaq_core.application.workspaces import Workspaces
        from thzdaq_core.domain.station.config import InstrumentConfig, StationConfig
        from thzdaq_core.domain.station.station import Station
        from thzdaq_gui.docks.setup import ConnectionsGroup
        from thzdaq_gui.workers import DeviceWorker
        from thzdaq_instruments.transport import SOCKET, ConnectionSpec, TransportPool
        from thzdaq_instruments.transport.fake import FakeLink

        pool = TransportPool(lambda spec: FakeLink({":OUTP? CH1": "ON"}))
        config = StationConfig(
            "bench",
            {"rigol": InstrumentConfig(
                "rigol.dp832a", ConnectionSpec(SOCKET, host="h", port=5555), title="Rigol"
            )},
        )  # fmt: skip
        station = Station(config, pause=time.sleep, pool=pool)
        workspaces = Workspaces(tmp_path, tmp_path / "data", MeasurementStore)
        assembled = assemble(
            Bench(station, Lanes()), workspaces, YamlProfiles(), LocalControl(),
            Processes(), FolderLibrary(tmp_path / LIBRARY),
        )  # fmt: skip

        class Client:
            """What the group needs of a session: its lab and its call queue."""

            lab = LocalLab(assembled)
            calls = DeviceWorker()

            def call(self, operation):
                return self.lab.call(operation)

        client = Client()
        group = ConnectionsGroup(client)
        (state,) = group.rows.values()
        assert state.text() == "not connected"
        station["rigol:1"].get_output()
        wait(lambda: state.text() == "connected")  # refreshed on its own
        pool.abort(next(iter(group.rows)))
        wait(lambda: state.text() == "error, reconnects")
        group.reset(next(iter(group.rows)))
        wait(lambda: state.text() == "connected")
        client.calls.stop()
        assembled.close()
        station.close()


class TestFolding:
    def test_controls_stay_below_the_scrolling_setup(self, window):
        box = window.docks["measure:two_sb.noise_temperature"].widget().box
        setup = box.scroll.widget()
        assert (
            box.devices_box.parent() is setup and box.parameters_box.parent() is setup
        )
        assert not setup.isAncestorOf(box.controls)
        assert box.footer.isAncestorOf(box.controls)

    def test_folded_devices_say_which_are_chosen(self, window, session):
        box = window.docks["measure:sis.power_vs_voltage"].widget().box
        box.devices_box.set_expanded(False)
        summary = box.devices_box.summary
        assert summary.isVisibleTo(box) and "SIS1" in summary.text()
        assert not box.devices_box.body.isVisibleTo(box)
        # Remembered for the next dock of this procedure
        again = type(box)(session, window.hub, box.procedure)
        assert not again.devices_box.expanded()
        box.devices_box.set_expanded(True)

    def test_a_missing_device_unfolds_the_devices(self, window, monkeypatch):
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
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
        wait(lambda: finished and not box.status().running)
        assert section.summary.text() == f"completed #{finished[0].id}"
        # The folded log shows its last line
        assert box.log_box.summary.text().startswith("saved ")


class TestRunGraphs:
    @staticmethod
    def corner(window, dock):
        return dock.dockAreaWidget().mapTo(
            window, dock.dockAreaWidget().rect().topLeft()
        )

    def test_four_graphs_of_a_run_make_a_grid(self, window, app):
        window.resize(1500, 900)
        titles = ["P-V", "I-V", "Y-V", "Tn-V"]
        window.hub.show_run(titles)
        app.processEvents()
        docks = [window.docks[f"graph:{t}"] for t in titles]
        areas = [d.dockAreaWidget() for d in docks]
        assert len(set(areas)) == 4
        assert all(d.isCurrentTab() and not d.isClosed() for d in docks)
        # 2 x 2: P-V | I-V over Y-V | Tn-V
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = [
            (p.x(), p.y()) for p in (self.corner(window, d) for d in docks)
        ]
        assert y0 == y1 and x0 == x2 and y2 == y3 and x1 == x3
        assert x1 > x0 and y2 > y0

    def test_groups_of_the_user_are_reused(self, window, app):
        import PySide6QtAds as QtAds

        iv, pv = window.docks["graph:I-V"], window.docks["graph:P-V"]
        window.dock_manager.addDockWidget(
            QtAds.RightDockWidgetArea, pv, iv.dockAreaWidget()
        )
        iv.dockAreaWidget().setCurrentDockWidget(window.docks["graph:Y-V"])
        before = len(window.docks.areas_of("graph"))
        window.hub.show_run(["P-V", "I-V"])
        app.processEvents()
        # Nothing moves: each is in front of the group it was in
        assert len(window.docks.areas_of("graph")) == before
        assert pv.isCurrentTab() and iv.isCurrentTab()
        assert pv.dockAreaWidget() is not iv.dockAreaWidget()

    def test_past_four_groups_graphs_wait_behind_tabs(self, window, app):
        titles = ["P-V", "I-V", "Y-V", "Tn-V", "P-IF"]
        window.hub.show_run(titles)
        app.processEvents()
        assert len(window.docks.areas_of("graph")) == 4
        assert not window.docks["graph:P-IF"].isClosed()
        assert all(window.docks[f"graph:{t}"].isCurrentTab() for t in titles[:4])

    def test_graphs_take_their_column(self, window, app):
        """Everything closed but the measurement: its graphs come left of it
        at full height and share the rest evenly."""
        window.resize(1500, 900)
        for name, dock in window.docks.items():
            if name != "measure:sis.current_vs_voltage" and not dock.isAutoHide():
                dock.toggleView(False)
        app.processEvents()
        window.hub.show_run(["V-t", "I-t"])
        app.processEvents()
        measurement = window.docks["measure:sis.current_vs_voltage"].dockAreaWidget()
        v_t, i_t = (window.docks[f"graph:{t}"] for t in ("V-t", "I-t"))
        for graph in (v_t, i_t):
            assert graph.dockAreaWidget().height() == measurement.height()
            assert self.corner(window, graph).x() < measurement.x()
        assert abs(v_t.dockAreaWidget().width() - i_t.dockAreaWidget().width()) <= 2
        width = measurement.width()
        assert v_t.dockAreaWidget().width() + i_t.dockAreaWidget().width() > width

    def test_pv_without_loads_opens_two_graphs_at_start(self, window, monkeypatch):
        box = window.docks["measure:sis.power_vs_voltage"].widget().box
        shown = []
        window.hub.run_requested.connect(
            lambda widgets: shown.append([w.title for w in widgets])
        )
        monkeypatch.setattr(box.runner, "start", lambda *a, **k: None)
        box.start()
        assert shown == [["P-V", "I-V"]]

    def test_graphs_button_shows_the_graphs_of_a_measurement(self, window):
        """Graphs, in its dock and on the bar on top: the graphs its
        parameters would fill come on screen, without a start."""
        shown = []
        window.hub.run_requested.connect(
            lambda widgets: shown.append([w.title for w in widgets])
        )
        box = window.docks["measure:sis.power_vs_voltage"].widget().box
        box.controls.btnGraphs.click()
        assert shown == [["P-V", "I-V"]]
        assert not window.docks["graph:P-V"].isClosed()
        window.runBar.choose("sis.current_vs_voltage")
        window.runBar.controls.btnGraphs.click()
        assert shown[-1] == ["I-V"]
        assert not box.status().running


class TestProcesses:
    def test_a_measurement_runs_in_processes_until_stopped(self, window, wait):
        processes = window.session.processes
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        box.form.set_values(
            {**FAST_IV, "voltage": sweep(0, 5e-3, 2000), "settle_time": 0.005}
        )
        box.start()
        wait(lambda: processes.items and processes.items[0].progress)
        (process,) = processes.items
        assert process.title == "SIS I-V curve"
        assert process.dock == "measure:sis.current_vs_voltage"
        assert process.progress[1] == 2000 and not process.can_abort
        assert window.docks["processes"].windowTitle() == "Processes (1)"
        assert window.processesWidget.tree.topLevelItemCount() == 1
        process.stop()
        wait(lambda: not processes.items and not box.status().running)
        assert window.docks["processes"].windowTitle() == "Processes"
        assert window.processesWidget.tree.topLevelItemCount() == 0

    def test_a_scan_shows_its_device_dock_unfolded(self, window, wait):
        from thzdaq_gui.collapsible import Collapsible
        from thzdaq_gui.docks.measure import ProcedureBox

        widget = window.docks["device:sis_bias_2"].widget()
        section = next(
            s for s in widget.findChildren(Collapsible) if s.title() == "I-V scan"
        )
        box = section.findChildren(ProcedureBox)[0]
        box.form.set_values(
            {**FAST_IV, "voltage": sweep(0, 5e-3, 2000), "settle_time": 0.005}
        )
        box.start()
        processes = window.session.processes
        wait(lambda: processes.items)
        (process,) = processes.items
        assert process.title == "SIS I-V curve · SIS2"
        assert process.dock == "device:sis_bias_2"
        window.docks["device:sis_bias_2"].toggleView(False)
        assert not section.expanded()
        window.processesWidget.show_process(process)
        assert window.docks.state("device:sis_bias_2") == "front"
        assert section.expanded()
        processes.stop_all()
        wait(lambda: not processes.items and not box.status().running)
        section.set_expanded(False)

    def test_polling_in_a_device_dock_is_a_process(self, window):
        processes = window.session.processes
        panel = window.docks["device:power_meter_1"].widget().panels[0]
        panel.interval.setValue(0.5)
        panel.monitor.setChecked(True)
        (process,) = processes.items
        assert process.title == "Monitor · R&S NRX"
        assert process.status == "every 0.5 s" and process.progress is None
        panel.interval.setValue(2)
        assert process.status == "every 2 s"
        process.stop()
        assert not panel.monitor.isChecked() and processes.items == []

    def test_chopper_rotation_follows_the_chopper(self, window, wait, bench):
        from thzdaq_gui.docks.devices import START_ROTATION, ChopperGroup

        group = window.docks["device:chopper_1"].widget().findChildren(ChopperGroup)[0]
        processes = window.session.processes
        # The last one is remembered across tests
        group.arguments[START_ROTATION].editors["frequency"].set(7.5)
        group.call(START_ROTATION)
        wait(lambda: processes.items)
        (process,) = processes.items
        assert process.title == "Rotation · Chopper" and process.status == "7.5 Hz"
        process.stop()
        wait(lambda: not processes.items)
        assert not bench.station.instrument("chopper_1").is_running()

    def test_a_layout_saved_before_processes_still_opens_it(
        self, window, session, tmp_path
    ):
        from thzdaq_gui.main_window import MainWindow

        window.docks.remove("processes")  # as a layout saved by an older version
        window.save_state()
        again = MainWindow(session, window.settings.fileName(), check_updates=False)
        again.confirm_exit = False
        again.show()
        dock = again.docks["processes"]
        # Back on its side bar, folded, not floating
        assert dock.isAutoHide() and not dock.isFloating() and not dock.isClosed()
        assert again.docks.state("processes") == "behind"
        again.show_dock("processes")
        assert again.docks.state("processes") == "front"
        again.close()


class TestRunBar:
    def test_the_bar_on_top_and_the_dock_of_the_chosen_measurement(self, window, app):
        window.resize(1500, 900)
        app.processEvents()
        bar = window.runBar
        assert bar.isVisible() and bar.chosen_name() == "sis.current_vs_voltage"
        dock = window.docks["measure:sis.current_vs_voltage"]
        assert not dock.isClosed() and dock.tabWidget().isVisible()
        assert not dock.isFloating()
        # One run, two views: the dock keeps its own controls
        box = dock.widget().box
        assert bar.controls.run is box
        assert box.controls.isVisibleTo(window)
        assert box.parameters_box.isVisibleTo(window)
        # The comment takes the free width of the bar
        assert bar.controls.comment.width() >= 320
        # Sized for its content once the window is shown
        assert dock.dockAreaWidget().width() >= 0.9 * dock.widget().sizeHint().width()
        assert all(
            d.isClosed()
            for n, d in window.docks.items()
            if n.startswith("measure:") and d is not dock
        )

    def test_every_dock_of_the_default_layout_shows_its_tab(self, window):
        hidden = [
            name
            for name, dock in window.docks.items()
            if not dock.isClosed() and not dock.isAutoHide()
            and not dock.tabWidget().isVisible()
        ]  # fmt: skip
        assert hidden == []

    def test_the_bar_and_the_dock_drive_one_run(self, window, wait):
        processes = window.session.processes
        bar = window.runBar
        bar.choose("sis.current_vs_voltage")
        iv = bar.controls.run
        iv.form.set_values(
            {**FAST_IV, "voltage": sweep(0, 5e-3, 2000), "settle_time": 0.005}
        )
        bar.controls.comment.setText("from the bar")
        bar.controls.comment.textEdited.emit("from the bar")
        assert iv.controls.comment.text() == "from the bar"
        bar.controls.btnStart.click()
        wait(lambda: iv.measurement is not None and bar.controls.btnStop.isEnabled())
        assert iv.measurement.comment == "from the bar"
        assert iv.controls.btnStop.isEnabled() and not iv.controls.btnStart.isEnabled()
        assert "Running" in bar.controls.progress.format()
        # Another measurement chosen: the first goes on
        bar.choose("sis.power_vs_voltage")
        pv = window.docks["measure:sis.power_vs_voltage"].widget().content().box
        assert bar.controls.run is pv and bar.controls.btnStart.isEnabled()
        assert iv.status().running
        assert [p.title for p in processes.items] == ["SIS I-V curve"]
        bar.choose("sis.current_vs_voltage")
        assert bar.controls.run is iv and bar.controls.btnStop.isEnabled()
        iv.controls.btnStop.click()  # stopped from the dock
        wait(lambda: not iv.status().running)
        assert bar.controls.btnStart.isEnabled()
        assert bar.controls.progress.format().startswith("cancelled")

    def test_the_settings_button_shows_the_dock(self, window, app):
        bar = window.runBar
        iv = window.docks["measure:sis.current_vs_voltage"]
        # Behind another tab: in front
        window.dock_manager.addDockWidgetTabToArea(
            window.docks["graph:P-V"], iv.dockAreaWidget()
        )
        window.docks["graph:P-V"].setAsCurrentTab()
        bar.btnParameters.click()
        assert iv.isCurrentTab()
        assert window.docks.state("measure:sis.current_vs_voltage") == "front"
        # Closed: back in its place
        area = iv.dockAreaWidget()
        iv.toggleView(False)
        bar.btnParameters.click()
        assert not iv.isClosed() and iv.dockAreaWidget() is area
        # Never placed: floating
        bar.choose("sis.power_vs_voltage")
        bar.btnParameters.click()
        pv = window.docks["measure:sis.power_vs_voltage"]
        assert not pv.isClosed() and pv.isFloating()

    def test_the_chosen_measurement_is_remembered(self, window, session):
        from thzdaq_gui.main_window import MainWindow

        combo = window.runBar.combo
        combo.activated.emit(combo.findData("sis.power_vs_voltage"))
        assert window.runBar.chosen_name() == "sis.power_vs_voltage"
        again = MainWindow(
            session, window.settings.fileName(), restore_layout=False,
            check_updates=False,
        )  # fmt: skip
        again.confirm_exit = False
        assert again.runBar.chosen_name() == "sis.power_vs_voltage"
        assert again.runBar.controls.run is again.measures.run("sis.power_vs_voltage")
        # The default layout has it on the right
        assert not again.docks["measure:sis.power_vs_voltage"].isClosed()
        again.close()


class TestDaemon:
    def test_the_window_shows_the_daemon(self, window, wait):
        from thzdaq_gui.models.daemon import OK

        model = window.daemon
        wait(lambda: model.state == OK)
        assert window.daemonIndicator.text() == "Simulator daemon"
        assert "1 measurement" not in window.daemonIndicator.toolTip()
        widget = window.daemonWidget
        sections = [
            widget.tree.topLevelItem(i).text(0)
            for i in range(widget.tree.topLevelItemCount())
        ]
        assert [s.split(" (")[0] for s in sections] == [
            "Problems", "Clients", "Measurements", "Scripts", "Queues", "Connections",
            "Polls",
        ]  # fmt: skip
        assert widget.btnStop.isEnabled() and not widget.btnStart.isEnabled()

    def test_a_running_script_is_shown(self, window, session, wait, tmp_path):
        import sys

        from thzdaq_api.scripts import StartScript, StopScript

        file = tmp_path / "slow.py"
        file.write_text("import time\ntime.sleep(60)\n")
        session.lab.assembled.scripts.grace = 0.2  # it ignores the cancel
        started = session.call(
            StartScript(
                path=str(file), python=(sys.executable,), workspace=str(tmp_path)
            )
        )
        tree = window.daemonWidget.tree

        def scripts():
            window.daemon.look()
            found = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
            items = [i for i in found if i.text(0).startswith("Scripts")]
            return [i.child(c).text(0) for i in items for c in range(i.childCount())]

        try:
            wait(lambda: scripts() == [f"{started.id} slow"])
        finally:
            session.call(StopScript(id=started.id))

    def test_a_person_chooses_what_agents_may_do(self, window, session, wait):
        from thzdaq_api.daemon import GetDaemonSettings
        from thzdaq_api.operation import Rights
        from thzdaq_api.rights import Decision

        agents = window.daemonWidget.agents
        wait(lambda: window.daemon.settings is not None)
        choices = agents.choices
        assert choices[Rights.SET].currentData() == Decision.ASK
        assert not choices[Rights.STATION].isEnabled()
        assert not choices[Rights.ANSWER].isEnabled()
        assert choices[Rights.RUN].isEnabled()
        set_choice = choices[Rights.SET]
        set_choice.setCurrentIndex(set_choice.findData(Decision.ALLOW))
        set_choice.activated.emit(set_choice.currentIndex())  # as a person picks
        kept = lambda: session.call(GetDaemonSettings()).agents[Rights.SET]  # noqa
        wait(lambda: kept() == Decision.ALLOW)
        wait(lambda: "set" in agents.summary.text())
        # The daemon refuses what it never changes: the choice shows what it keeps
        window.daemon.let_agents(Rights.STATION, Decision.ALLOW)
        wait(lambda: not agents.status.isHidden())
        assert "stay deny" in agents.status.text()
        assert choices[Rights.STATION].currentData() == Decision.DENY

    def test_a_lost_daemon_is_shown_and_started_again(
        self, window, session, wait, monkeypatch
    ):
        from thzdaq_api.errors import ErrorCode, LabError
        from thzdaq_gui.models.daemon import LOST, OK

        class Gone:
            def call(self, operation):
                raise LabError(ErrorCode.UNREACHABLE, "No simulator daemon runs")

        lab = session.lab
        monkeypatch.setattr(session, "lab", Gone())
        window.daemon.look()
        wait(lambda: window.daemon.state == LOST)
        assert not window.bannerBar.isHidden()
        assert "No simulator daemon runs" in window.lostBanner.text.text()
        assert window.daemonWidget.btnStart.isEnabled()
        # Start: the session connects again (the lab of the test is there)
        monkeypatch.setattr(session, "lab", lab)
        window.daemonWidget.btnStart.click()
        wait(lambda: window.daemon.state == OK)
        assert window.bannerBar.isHidden()


SLOW_IV = {
    "voltage": {"start": 0.0, "stop": 5e-3, "points": 2000},
    "settle_time": 0.01,
    "first_point_delay": 0.0,
}


def sweep_bias(session, ref="sis_bias_1"):
    """Another client's measurement that sweeps a bias while a test acts."""
    from thzdaq_api.measurements import StartMeasurement

    return session.call(
        StartMeasurement(
            procedure="sis.current_vs_voltage",
            parameters=SLOW_IV,
            devices={"bias": ref},
        )
    )


def ended(session, run):
    from thzdaq_api.measurements import CancelMeasurement, WaitMeasurement

    session.call(CancelMeasurement(id=run.id))
    return session.call(WaitMeasurement(id=run.id, timeout=10))


class TestConflicts:
    def test_a_start_on_a_swept_device_is_asked_once(
        self, window, session, wait, monkeypatch
    ):
        from thzdaq_api.measurement_file import CONFLICTS

        other = sweep_bias(session)
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        box.form.set_values(FAST_IV)
        box.devices.combos["bias"].setCurrentIndex(
            box.devices.combos["bias"].findData("sis_bias_1")
        )
        asked, answers = [], [QMessageBox.No, QMessageBox.Yes]
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **k: asked.append(a[2]) or answers.pop(0),
        )
        box.start()
        wait(lambda: len(asked) == 1)
        assert f"#{other.id}" in asked[0] and "Start anyway?" in asked[0]
        assert box.status().outcome == "not started: a device is in use"
        finished = []
        box.runner.finished.connect(finished.append)
        box.start()  # yes: it goes on and notes the conflict
        wait(lambda: finished)
        assert finished[0].metadata[CONFLICTS][0]["run"] == other.id
        model = session.measurements
        row = model.items.index(finished[0])
        assert model.data(model.index(row, 5), Qt.DecorationRole) is not None
        assert "Conflicts accepted" in model.data(model.index(row, 5), Qt.ToolTipRole)
        ended(session, other)

    def test_check_says_whether_it_would_start(self, window, session, monkeypatch):
        box = window.docks["measure:sis.current_vs_voltage"].widget().box
        box.form.set_values(FAST_IV)
        told = []
        monkeypatch.setattr(
            QMessageBox, "information", lambda *a, **k: told.append(a[2])
        )
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: told.append(a[2]))
        box.check()
        assert told[-1].startswith("Ready to start: 6 steps on SIS")
        assert not session.running()  # nothing started
        other = sweep_bias(session, box.mapping()["bias"])
        box.check()
        assert f"#{other.id}" in told[-1]
        ended(session, other)

    def test_a_device_dock_shows_who_sweeps_it_and_asks(
        self, window, session, bench, wait, monkeypatch
    ):
        widget = window.docks["device:sis_bias_1"].widget()
        assert widget.use.isHidden()
        other = sweep_bias(session)
        wait(lambda: not widget.use.isHidden())
        assert (
            f"#{other.id}" in widget.use.text() and "sweeps SIS1" in widget.use.text()
        )
        asked = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes,
        )
        panel = widget.panels[0]
        voltage = next(q for q in panel.quantities if q.key == "voltage_set")
        panel.write(voltage, 1e-3)  # refused, asked, set anyway
        wait(lambda: asked and not panel.fields["voltage_set"].pending)
        assert f"#{other.id}" in asked[0]
        wait(lambda: panel.fields["voltage_set"].value() == 1e-3)
        # The sweep notes who changed its device (and restores it at its end)
        noted = ended(session, other).conflicts
        assert [(c["key"], c["by"]) for c in noted] == [("voltage_set", "gui")]
        wait(lambda: widget.use.isHidden())

    def test_the_safe_state_button_sets_the_profile_values(
        self, window, session, bench, wait, monkeypatch
    ):
        from thzdaq_gui import profile as fmt

        told = []
        monkeypatch.setattr(
            QMessageBox, "information", lambda *a, **k: told.append(a[2])
        )
        window.safeState.trigger()  # the profile has none yet
        assert "no safe state" in told[-1]
        edited = fmt.changed(session.profile().profile)
        edited[fmt.SAFETY] = {fmt.SAFE_STATE: {"sis_bias_1": {"voltage_set": 0.0}}}
        session.update_profile(edited)
        bench.station.device("sis_bias_1").set_voltage(2e-3)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        window.safeState.trigger()
        wait(lambda: len(told) == 2)
        assert "sis_bias_1 voltage_set → 0.0: set" in told[-1]
        voltage = bench.station.device("sis_bias_1").get_voltage()
        assert abs(voltage) < 1e-4
