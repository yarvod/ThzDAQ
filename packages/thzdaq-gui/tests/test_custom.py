"""The bench's own measurements in the window: in the list on top (group
Custom) and Ctrl+K, made from a blank or an example, their forms in the
drop-down of the bar, run with what their script prints in the Log tab, and
their scripts in the dock of a file: saved, checked, completed, changed
outside, kept by a measurement."""

import msgspec
import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox
from thzdaq_api.custom import LIBRARY

from thzdaq_gui.dock_names import CODE, MEASURE, dock_name

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


def code_dock(window, path):
    return dock_name(CODE, str(path.resolve()))


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


def test_a_new_measurement_opens_in_the_dock_of_its_file(window, wait, named, library):
    named["name"] = "scan"
    window.code.new_measurement()
    path = library / "scan.py"
    assert path.exists() and 'with lab.measurement("scan"' in path.read_text()
    dock = window.docks[code_dock(window, path)]
    assert not dock.isClosed() and dock.isCurrentTab()
    assert dock.windowTitle() == "scan.py"
    appears(window, wait, "custom.scan")
    window.code.open(path)  # again: the same dock
    assert sum(1 for n in window.docks if n.startswith(f"{CODE}:")) == 1


def test_an_example_goes_into_the_library_under_a_free_name(
    window, wait, named, library
):
    (library / "sweep.py").write_text("taken\n")
    window.code.from_example("sweep")
    assert (
        (library / "sweep_2.py").read_text(encoding="utf-8").startswith('"""Bias sweep')
    )


def test_the_dock_of_a_file_saves_checks_and_asks_before_it_closes(
    window, wait, library, monkeypatch
):
    path = library / "told.py"
    path.write_text(TOLD, encoding="utf-8")
    appears(window, wait, "custom.told")
    window.code.open(path)
    name = code_dock(window, path)
    widget = window.code.widgets[name]
    widget.editor.setPlainText(TOLD + "print(nothing)\n")
    assert window.docks[name].windowTitle() == "told.py •"
    widget.save()
    wait(lambda: path.read_text(encoding="utf-8").endswith("print(nothing)\n"))
    wait(
        lambda: widget.problems.count() and "nothing" in widget.problems.item(0).text()
    )
    assert 9 in widget.editor.problems  # its line is marked
    assert window.docks[name].windowTitle() == "told.py"
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
    window.docks[name].requestCloseDockWidget()
    assert name in window.docks
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    window.docks[name].requestCloseDockWidget()
    assert name not in window.docks


def test_a_file_changed_outside_is_taken_or_asked_about(window, wait, library):
    path = library / "told.py"
    path.write_text(TOLD, encoding="utf-8")
    window.code.open(path)
    widget = window.code.widgets[code_dock(window, path)]
    path.write_text(TOLD + "# by an agent\n", encoding="utf-8")
    wait(lambda: widget.text.endswith("# by an agent\n"))
    widget.editor.insertPlainText("# mine\n")
    path.write_text(TOLD, encoding="utf-8")
    wait(lambda: not widget.banner.isHidden())
    assert "# mine" in widget.text
    widget.reload()
    assert widget.text == TOLD and widget.banner.isHidden()


def test_completions_know_the_bench(window, wait, library):
    path = library / "told.py"
    path.write_text(TOLD, encoding="utf-8")
    window.code.open(path)
    model = window.code.widgets[code_dock(window, path)].model
    text = 'import thzdaq\nlab = thzdaq.connect()\nbias = lab["sis_bias_1"]\nbias.vo'
    assert "sis_bias_2" in model.complete('x = lab["sis', 1, len('x = lab["sis'))
    words = model.complete(text, 4, len("bias.vo"))
    assert "voltage_set" in words and "voltage" in words
    declared = 'bias = device("SIS bias", kind="sis_bias")\nbias.act'
    assert "active" in model.complete(declared, 2, len("bias.act"))
    assert "connect" in model.complete("import thzdaq\nthzdaq.con", 2, 10)


def test_the_script_a_measurement_kept_opens_as_its_text(window, wait, named, library):
    window.code.open_text("#12 scan.py", TOLD)
    (name,) = [n for n in window.docks if n.startswith(f"{CODE}:#")]
    widget = window.code.widgets[name]
    assert window.docks[name].windowTitle() == "#12 scan.py"
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
