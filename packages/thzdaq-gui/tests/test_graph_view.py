"""A graph as people see it: colours of its curves (a curve keeps the colour it
got, a new one never repeats a colour on its graph while the palette has a free
one) and the values next to the mouse."""

from PySide6.QtCore import QPointF
from thzdaq_api.measurements import PlotInfo
from thzdaq_gui import theme
from thzdaq_gui.graphs import Axis, GraphWidget, MapGraphWidget


def colors(graph):
    return {
        key: item.opts["pen"].color().name().lower()
        for key, item in graph.items.items()
    }


def test_a_new_curve_after_a_removed_one_takes_a_colour_not_on_the_graph(app):
    graph = GraphWidget("P-t", Axis(), Axis())
    for n in range(3):
        graph.append(n, f"curve {n}", 0.0, 1.0)
    graph.remove(0)  # the first colour is free again
    before = colors(graph)
    graph.append(3, "curve 3", 0.0, 1.0)
    assert colors(graph)[1] == before[1] and colors(graph)[2] == before[2]
    assert len(set(colors(graph).values())) == 3
    assert colors(graph)[3] == theme.COLORS[0].lower()
    graph.close()


def hover(widget, view, plot, x, y):
    """The mouse over a point of the plot, in its coordinates."""
    position = plot.getViewBox().mapViewToScene(QPointF(x, y))
    view.scene().sigMouseMoved.emit(position)


def test_values_next_to_the_mouse_in_the_units_of_the_axes(app):
    graph = GraphWidget("I-V", Axis("Voltage, mV"), Axis("Current", "A"))
    graph.resize(500, 400)
    graph.show()
    plot = graph.plot.getPlotItem()
    plot.setXRange(0, 5, padding=0)
    plot.setYRange(0, 2e-4, padding=0)
    app.processEvents()
    hover(graph, graph.plot, plot, 2.5, 1e-4)
    assert graph.cursor.text() == "x = 2.5 mV\ny = 100 µA"
    # Off the plot's area (over an axis) it is gone
    graph.plot.scene().sigMouseMoved.emit(QPointF(1, 1))
    assert graph.cursor.text() == ""
    graph.close()


def test_a_map_shows_z_of_the_cell_under_the_mouse(app):
    spec = PlotInfo(
        "tn", "Tn", "map", "a", "b", x_label="SIS1, mV", y_label="SIS2, mV",
        kind="map", z="tn", z_label="K",
    )  # fmt: skip
    graph = MapGraphWidget(spec)
    graph.resize(500, 400)
    graph.show()
    for a in (1.0, 2.0):
        for b in (1.0, 2.0):
            graph.add_record({"a": a, "b": b, "tn": 10 * a + b})
    plot = graph.cursor.plot
    plot.setXRange(0, 3, padding=0)
    plot.setYRange(0, 3, padding=0)
    app.processEvents()
    hover(graph, graph.view, plot, 2.1, 0.9)
    assert graph.cursor.text() == "x = 2.1 mV\ny = 0.9 mV\nz = 21 K"
    hover(graph, graph.view, plot, 0.2, 0.2)  # no cell there
    assert graph.cursor.text() == "x = 0.2 mV\ny = 0.2 mV"
    graph.close()
