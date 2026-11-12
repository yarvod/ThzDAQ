"""Colours of curves: a curve keeps the colour it got, a new one never repeats
a colour on its graph while the palette has a free one."""

from thzdaq_gui import theme
from thzdaq_gui.graphs import Axis, GraphWidget


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
