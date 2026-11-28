"""Graphs of the bench's own measurements (a library script's plots, its
m.plot, a file of one) are a person's to rename and delete; those of the
built-in procedures stay. A deleted one comes back when a run draws into it;
one whose plot its script no longer declares goes when nothing is on it. A
map marks the cell its run measured last until the run ends."""

import pytest
from PySide6.QtWidgets import QDialog
from thzdaq_api.measurement_file import Measurement
from thzdaq_api.measurements import PlotInfo, ProcedureSummary
from thzdaq_gui.graphs import GraphDialog, GraphHub, OwnGraphs

IV = PlotInfo("iv", "I-V", "iv", "voltage", "current", x_label="Voltage, mV")
SWEEP = PlotInfo(
    "p", "Mine P-V", "pv", "voltage", "power", x_label="Voltage, mV",
    y_label="Power, dBm", caption="P-V of mine",
)  # fmt: skip
GRID = PlotInfo(
    "tn", "Mine Tn", "grid", "a", "b", kind="map", z="tn", z_label="K",
)  # fmt: skip
BUILTIN = ProcedureSummary("sis.current_vs_voltage", "SIS I-V", "", (IV,))


def mine(*plots) -> ProcedureSummary:
    return ProcedureSummary("custom.mine", "Mine", "", plots)


@pytest.fixture
def hub(app):
    hub = GraphHub([BUILTIN, mine(SWEEP, GRID)], lambda operation: None)
    yield hub
    hub.close()


def told(signal) -> list:
    heard = []
    signal.connect(lambda *args: heard.append(args[0] if args else None))
    return heard


def run(number=7) -> Measurement:
    return Measurement("custom.mine", title="Mine", id=number)


def test_only_the_bench_own_graphs_offer_edit_and_delete(hub):
    assert hasattr(hub.graph("Mine P-V"), "btnDelete")
    assert hasattr(hub.graph("Mine Tn"), "btnDelete")  # a map too
    assert not hasattr(hub.graph("I-V"), "btnDelete")
    built_in = hub.graph("I-V")
    hub.remove(built_in)  # never deleted
    assert hub.graphs["I-V"] is built_in and "I-V" in hub.titles()


def test_a_hub_without_the_catalog_offers_no_edits(app):
    hub = GraphHub((), lambda operation: None)  # the plots window
    hub.register_plots([SWEEP])
    assert not hasattr(hub.graph("Mine P-V"), "btnDelete")
    hub.close()


def test_a_person_renames_an_own_graph_and_empty_fields_are_its_plots(hub, monkeypatch):
    def answer(names):
        def exec_(dialog):
            for field, text in zip((dialog.title, dialog.x, dialog.y), names):
                field.setText(text)
            return QDialog.Accepted

        monkeypatch.setattr(GraphDialog, "exec", exec_)

    graph = hub.graph("Mine P-V")
    renamed, remember = told(hub.graph_renamed), told(hub.custom_changed)
    answer(("Hot and cold", "", "P, dBm"))
    graph.btnEdit.click()
    assert renamed == [graph] and remember
    assert graph.shown_title() == hub.shown_title("Mine P-V") == "Hot and cold"
    assert (graph.x.label, graph.y.label) == ("Voltage, mV", "P, dBm")
    assert hub.graph_named("Hot and cold") == "Mine P-V"  # agents name it so too
    assert hub.own.names == {"Mine P-V": ("Hot and cold", "", "P, dBm")}
    answer(("", "", ""))
    graph.btnEdit.click()
    assert graph.shown_title() == "P-V of mine" and graph.y.label == "Power, dBm"
    assert graph.title == "Mine P-V"  # what runs draw into stays


def test_a_deleted_graph_stays_deleted_until_a_run_draws_into_it(hub):
    graph = hub.graph("Mine P-V")
    asked = told(hub.graph_removed)
    graph.btnDelete.click()  # the window asks the person, then removes it
    assert asked == [graph]
    hub.remove(graph)
    assert "Mine P-V" not in hub.titles() and "Mine P-V" not in hub.graphs
    assert hub.own.deleted == ("Mine P-V",)
    added = told(hub.titles_added)
    hub.set_procedures([BUILTIN, mine(SWEEP, GRID)])  # the catalog again
    assert added == [] and "Mine P-V" not in hub.titles()
    hub.feed(run(), (SWEEP,), "pv", {"voltage": 1e-3, "power": -30.0})
    again = hub.graphs["Mine P-V"]
    assert again is not graph and not again.empty()
    assert hub.own.deleted == () and "Mine P-V" in hub.titles()


def test_deleted_and_renamed_graphs_are_remembered(app):
    own = OwnGraphs({"Mine Tn": ("Grid", "", "")}, ("Mine P-V",))
    hub = GraphHub([BUILTIN, mine(SWEEP, GRID)], lambda operation: None)
    hub.restore_own(own)
    assert "Mine P-V" not in hub.titles()
    assert hub.shown_title("Mine Tn") == "Grid"
    assert hub.graph("Mine Tn").shown_title() == "Grid"
    hub.close()


def test_a_plot_the_script_dropped_goes_when_nothing_is_on_it(hub):
    hub.graph("Mine Tn")  # built, empty
    hub.feed(run(), (SWEEP,), "pv", {"voltage": 1e-3, "power": -30.0})
    dropped = told(hub.graphs_dropped)
    hub.set_procedures([BUILTIN, mine()])  # the script declares neither now
    assert dropped == [["Mine Tn"]]
    assert "Mine Tn" not in hub.titles() and "Mine Tn" not in hub.graphs
    assert "Mine P-V" in hub.titles()  # it shows a curve: it stays


def test_agents_clear_graphs_whole_or_one_measurements_curves(hub):
    for number in (7, 8):
        hub.feed(run(number), (SWEEP,), "pv", {"voltage": 1e-3, "power": -30.0})
    hub.feed(run(7), (IV,), "iv", {"voltage": 1e-3, "current": 1e-5})
    hub.graph("Mine Tn")  # nothing on it
    assert hub.clear(hub.titles(), measurement=8) == ["P-V of mine"]
    assert [key[0] for key in hub.graphs["Mine P-V"].items] == [7]
    assert hub.clear(hub.titles()) == ["I-V", "P-V of mine"]
    assert all(widget.empty() for widget in hub.graphs.values())
    assert hub.graph_named("graph:I-V") == "I-V" and hub.graph_named("I-W") is None


def test_a_map_marks_the_cell_its_run_measured_last_until_it_ends(hub):
    measurement = run()
    hub.feed(measurement, (GRID,), "grid", {"a": 1.0, "b": 2.0, "tn": 30.0})
    graph = hub.graphs["Mine Tn"]
    assert list(zip(*graph.current.getData())) == [(1.0, 2.0)]
    hub.end_measurement(run(8))  # another run's end
    assert len(graph.current.getData()[0]) == 1
    hub.end_measurement(measurement)
    assert len(graph.current.getData()[0]) == 0
