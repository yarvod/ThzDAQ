"""The bench's own measurements in the window: in the list on top (group
Custom) and Ctrl+K, made from a blank or an example, their forms in the
drop-down of the bar, run with what their script prints in the Log tab, and
their scripts in tabs of the Editor dock: saved, checked, completed, changed
outside, kept by a measurement, closed asking about what is not saved."""

import msgspec
import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox
from thzdaq_api.custom import LIBRARY

from thzdaq_gui.dock_names import CODE, EDITOR, MEASURE, dock_name
from thzdaq_gui.review import Source

TOLD = '''"""Told

Prints what it was given.
"""
from thzdaq import value

settle = value("Settle", 10, unit="ms")
print("settle", float(settle))
'''


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / LIBRARY
    folder.mkdir()
    return folder


@pytest.fixture
def named(monkeypatch):
    """The name a person types when asked for one."""
    answer = {"name": "", "ok": True}
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *a, **k: (answer["name"] or k["text"], answer["ok"]),
    )
    return answer


def tab_of(window, path):
    """The tab of a file in Editor."""
    return window.code.widgets[str(path.resolve())]


def titles(window):
    tabs = window.code.tabs
    return [tabs.title(widget) for widget in tabs.widgets()]


def appears(window, wait, procedure):
    """In the list of the bar; its form."""
    wait(lambda: procedure in window.runBar.items, timeout=10)
    return window.measures.form(procedure)


def test_a_script_of_the_library_is_a_measurement_of_the_window(window, wait, library):
    (library / "told.py").write_text(TOLD, encoding="utf-8")
    form = appears(window, wait, "custom.told")
    bar = window.runBar
    name = dock_name(MEASURE, "custom.told")
    (entry,) = [e for e in window.places.listed() if e.name == name]
    assert (entry.title, entry.section, entry.group) == ("Told", "Measures", "Custom")
    # Beside the built-in ones: the catalog told is all of it
    assert "sis.current_vs_voltage" in bar.items
    assert form.titleLabel.text() == "Told"
    assert not form.btnCode.isHidden()
    assert [p.name for p in form.box.info.parameters] == ["settle"]
    # Found (Ctrl+K): chosen on top, its parameters open, the bar drives its run
    window.places.show(name)
    assert bar.chosen_name() == "custom.told"
    assert bar.parameters.isVisible() and bar.parameters.shown is form
    assert bar.controls.run is form.box
    bar.parameters.hide()
    (library / "told.py").unlink()
    wait(lambda: "custom.told" not in bar.items, timeout=10)
    assert "custom.told" not in window.measures.forms
    # Gone with its script: the default is chosen
    assert bar.chosen_name() == "sis.current_vs_voltage"
    assert bar.controls.run is window.measures.run("sis.current_vs_voltage")


def test_a_measurement_runs_from_the_bar_and_logs_what_it_prints(window, wait, library):
    (library / "told.py").write_text(TOLD, encoding="utf-8")
    form = appears(window, wait, "custom.told")
    window.runBar.choose("custom.told")
    form.box.form.set_values({"settle": 0.02})
    window.runBar.controls.btnStart.click()
    log = window.logWidget

    def told(text):
        return any(
            r.measurement == "custom.told" and text in r.text for r in log.records
        )

    wait(lambda: told("settle 0.02"), timeout=20)
    wait(lambda: not form.box.runner.running, timeout=20)
    wait(lambda: told("completed"), timeout=5)
    # Of this measurement alone, in the Log tab
    log.show_measurement("custom.told")
    assert log.filter.currentText() == "Told"
    shown = log.text.toPlainText()
    assert "settle 0.02" in shown and "Told" in shown
    assert all("custom.told" == r.measurement for r in log.records if r.text in shown)


def test_the_tab_of_a_library_script_chooses_its_measurement(
    window, wait, library, tmp_path
):
    bar, tabs = window.runBar, window.code.tabs
    told = library / "told.py"
    told.write_text(TOLD, encoding="utf-8")
    # Opened before the daemon has described it: chosen once it is listed
    window.code.open(told)
    wait(lambda: bar.chosen_name() == "custom.told", timeout=10)
    # A script outside the library chooses nothing
    free = tmp_path / "free.py"
    free.write_text("print(1)\n", encoding="utf-8")
    bar.choose("sis.current_vs_voltage")
    window.code.open(free)
    assert bar.chosen_name() == "sis.current_vs_voltage"
    # Its tab made current again, or opened again while current: chosen
    tabs.show_tab(tab_of(window, told))
    assert bar.chosen_name() == "custom.told"
    bar.choose("sis.current_vs_voltage")
    window.code.open(told)
    assert bar.chosen_name() == "custom.told"
    # One not listed yet waits; choosing another in the bar cancels it
    (library / "later.py").write_text(TOLD, encoding="utf-8")
    window.code.open(library / "later.py")
    bar.choose("sis.current_vs_voltage")
    appears(window, wait, "custom.later")
    assert bar.chosen_name() == "sis.current_vs_voltage"


def test_a_new_measurement_opens_in_a_tab_of_editor(window, wait, named, library):
    tabs = window.code.tabs
    assert tabs.currentWidget() is not tabs.tabs  # nothing open: the hint
    named["name"] = "scan"
    window.code.new_measurement()
    path = library / "scan.py"
    assert path.exists() and 'with lab.measurement("scan"' in path.read_text()
    widget = tab_of(window, path)
    assert tabs.current() is widget and titles(window) == ["scan.py"]
    # Editor unfolds in front; files are no docks of their own
    assert window.docks.state(EDITOR) == "front"
    assert not any(name.startswith(f"{CODE}:") for name in window.docks)
    appears(window, wait, "custom.scan")
    assert window.runBar.chosen_name() == "custom.scan"  # its tab is current
    (library / "told.py").write_text(TOLD, encoding="utf-8")
    window.code.open(library / "told.py")
    assert titles(window) == ["scan.py", "told.py"]
    window.code.open(path, 3)  # again: the same tab, at the line
    assert titles(window) == ["scan.py", "told.py"] and tabs.current() is widget
    assert widget.editor.textCursor().blockNumber() == 2
    # Processes lead to a file run from it: its tab
    window.code.tabs.show_tab(tab_of(window, library / "told.py"))
    window.show_dock(dock_name(CODE, str(path.resolve())))
    assert tabs.current() is widget


def test_tabs_close_by_their_button_or_a_middle_click(window, library, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QTabBar

    paths = []
    for name in ("one", "two"):
        paths.append(library / f"{name}.py")
        paths[-1].write_text(TOLD, encoding="utf-8")
        window.code.open(paths[-1])
    tabs = window.code.tabs
    one, two = (tab_of(window, path) for path in paths)
    one.editor.insertPlainText("# more\n")
    assert titles(window) == ["one.py ●", "two.py"]
    # Unsaved: its close button asks, Cancel keeps it
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    close = tabs.tabs.tabBar().tabButton(0, QTabBar.RightSide)
    close.click()
    assert titles(window) == ["one.py ●", "two.py"]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    close.click()
    assert titles(window) == ["two.py"]
    assert str(paths[0].resolve()) not in window.code.widgets
    assert not window.code.unsaved()
    # A middle click closes a tab too; with none the hint is back
    bar = tabs.tabs.tabBar()
    at = QPointF(bar.tabRect(0).center())
    released = QMouseEvent(
        QEvent.MouseButtonRelease, at, at, Qt.MiddleButton, Qt.NoButton, Qt.NoModifier
    )
    tabs.eventFilter(bar, released)
    assert titles(window) == [] and window.code.widgets == {}
    assert tabs.currentWidget() is not tabs.tabs


def test_an_example_goes_into_the_library_under_a_free_name(
    window, wait, named, library
):
    (library / "sweep.py").write_text("taken\n")
    window.code.from_example("sweep")
    assert (
        (library / "sweep_2.py").read_text(encoding="utf-8").startswith('"""Bias sweep')
    )


def test_the_tab_of_a_file_saves_checks_and_asks_before_it_closes(
    window, wait, library, monkeypatch
):
    path = library / "told.py"
    path.write_text(TOLD, encoding="utf-8")
    appears(window, wait, "custom.told")
    window.code.open(path)
    widget = tab_of(window, path)
    tabs = window.code.tabs
    widget.editor.setPlainText(TOLD + "print(nothing)\n")
    assert tabs.title(widget) == "told.py ●"
    assert window.code.unsaved()
    widget.save()
    wait(lambda: path.read_text(encoding="utf-8").endswith("print(nothing)\n"))
    wait(
        lambda: widget.problems.count() and "nothing" in widget.problems.item(0).text()
    )
    assert 9 in widget.editor.problems  # its line is marked
    assert tabs.title(widget) == "told.py"
    # The form follows the script saved
    widget.editor.setPlainText(
        TOLD.replace(
            'settle = value("Settle", 10, unit="ms")',
            'settle = value("Settle", 10, unit="ms")\n' 'n = value("Points", 5)',
        )
    )
    widget.save()
    content = appears(window, wait, "custom.told")
    wait(lambda: "n" in content.box.form.editors, timeout=10)
    # Unsaved: closing asks, Cancel keeps it
    widget.editor.insertPlainText("# more\n")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    assert not tabs.request_close(widget)
    assert tabs.widgets() == [widget]
    # Save: saved, then closed
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    assert tabs.request_close(widget)
    assert tabs.widgets() == []
    wait(lambda: "# more" in path.read_text(encoding="utf-8"))


def test_a_file_changed_outside_is_shown_hunk_by_hunk_or_asked_about(
    window, wait, library
):
    path = library / "told.py"
    path.write_text(TOLD, encoding="utf-8")
    window.code.open(path)
    widget = tab_of(window, path)
    editor = widget.editor
    # Nothing unsaved: the change is the text's, shown to keep or undo
    path.write_text(TOLD + "# by an agent\n", encoding="utf-8")
    wait(lambda: editor.review is not None)
    assert editor.review.source is Source.OUTSIDE
    assert widget.text.endswith("# by an agent\n") and not widget.unsaved()
    editor.hunkButtons[0].leave.click()  # undone here: the file still has it
    assert widget.text == TOLD and widget.unsaved() and editor.review is None
    widget.save()
    wait(lambda: path.read_text(encoding="utf-8") == TOLD)
    # Changes here: a banner asks; Compare takes the file's hunks or not
    editor.insertPlainText("# mine\n")
    path.write_text(TOLD + "# theirs\n", encoding="utf-8")
    wait(lambda: not widget.banner.isHidden())
    assert "# mine" in widget.text and editor.review is None
    widget.compare()
    assert editor.review.source is Source.COMPARED and widget.banner.isHidden()
    assert "# mine" in widget.text  # mine until a hunk of the file is taken
    editor.reviewBar.takeAll.click()
    assert widget.text == TOLD + "# theirs\n" and not widget.unsaved()
    # Reload drops what is here; Keep mine keeps it, not saved
    editor.insertPlainText("# mine\n")
    path.write_text(TOLD, encoding="utf-8")
    wait(lambda: not widget.banner.isHidden())
    widget.keep_mine()
    assert "# mine" in widget.text and widget.unsaved()
    path.write_text(TOLD + "# again\n", encoding="utf-8")
    wait(lambda: not widget.banner.isHidden())
    widget.reload()
    assert widget.text == TOLD + "# again\n" and widget.banner.isHidden()
    assert not widget.unsaved()


def test_completions_know_the_bench(window, wait, library):
    path = library / "told.py"
    path.write_text(TOLD, encoding="utf-8")
    window.code.open(path)
    model = tab_of(window, path).model
    text = 'import thzdaq\nlab = thzdaq.connect()\nbias = lab["sis_bias_1"]\nbias.vo'
    assert "sis_bias_2" in model.complete('x = lab["sis', 1, len('x = lab["sis'))
    words = model.complete(text, 4, len("bias.vo"))
    assert "voltage_set" in words and "voltage" in words
    declared = 'bias = device("SIS bias", kind="sis_bias")\nbias.act'
    assert "active" in model.complete(declared, 2, len("bias.act"))
    assert "connect" in model.complete("import thzdaq\nthzdaq.con", 2, 10)


def test_the_script_a_measurement_kept_opens_as_its_text(window, wait, named, library):
    window.code.open_text("#12 scan.py", TOLD)
    window.code.open_text("#12 scan.py", TOLD)  # again: a tab of its own
    assert titles(window) == ["#12 scan.py", "#12 scan.py"]
    widget = window.code.tabs.current()
    assert not widget.runButton.isEnabled()
    named["name"] = "scan_again"
    widget.save()  # into the library, under a name
    assert (library / "scan_again.py").read_text(encoding="utf-8") == TOLD


PV = '''"""PV"""
from thzdaq import device, plot, value

bias = device("SIS bias", kind="sis_bias")
voltage = value("Bias voltage", "0:7:11", unit="mV")
pv = plot("P-V of mine", table="pv", x="voltage", y="power", into="P-V")
'''


def spec(title, x_label, y_label, into=None):
    from thzdaq_api.measurements import PlotInfo

    return PlotInfo(
        key=title, title=title, table="t", x="x", y="y",
        x_label=x_label, y_label=y_label, into=into,
    )  # fmt: skip


def test_a_plot_goes_into_a_graph_of_the_window_of_the_same_units(window):
    told = []
    hub = window.hub
    iv = hub.specs["I-V"]
    same = spec("mine", iv.x_label, iv.y_label, into="I-V")
    other = spec("power", iv.x_label, "Power, dBm", into="I-V")
    missing = spec("lost", iv.x_label, iv.y_label, into="No such graph")
    routed = hub.route((same, other, missing), told.append)
    assert [s.title for s in routed] == ["I-V", "power", "lost"]
    assert len(told) == 2
    assert "not those of 'I-V'" in told[0] and "no graph 'No such graph'" in told[1]


def test_the_form_chooses_where_a_declared_plot_goes(window, wait, library):
    (library / "pv.py").write_text(PV, encoding="utf-8")
    content = appears(window, wait, "custom.pv")
    combo = content.graphs.combos["custom.pv.pv"]
    assert combo.currentData() == "P-V"  # into= of the script first
    (declared,) = content.box.info.plots
    assert content.box.chosen_plots((declared,))[0].into == "P-V"
    combo.setCurrentIndex(combo.findData(None))  # a graph of its own
    assert content.box.chosen_plots((declared,))[0].into is None
    window.close()


def test_data_draws_the_plots_a_script_added(window):
    from thzdaq_api.measurement_file import PLOTS, Measurement
    from thzdaq_api.measurements import PlotInfo

    measurement = Measurement("script:scan", "scan", 7)
    for v in (0.0, 1e-3, 2e-3):
        measurement.append("scan", {"voltage": v, "power": -30.0 + v})
    plot = PlotInfo(key="script:scan.scan.voltage.power", title="Power of scan",
                    table="scan", x="voltage", y="power")  # fmt: skip
    measurement.metadata[PLOTS] = [msgspec.to_builtins(plot)]
    window.graphs.plot(measurement)
    graph = window.hub.graphs["Power of scan"]
    assert graph.points and len(next(iter(graph.points.values()))) == 3
