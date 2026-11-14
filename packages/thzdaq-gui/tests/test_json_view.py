"""The JSON tree of Details (offscreen): it folds as an editor's, makes its
lines when unfolded, pages long arrays and copies what is selected."""

import json

from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QGuiApplication
from thzdaq_gui.json_view import PAGE, JsonModel, JsonView, dotted, page_size

VALUE = {
    "parameters": {"start": 0.001, "points": 3, "note": "a\nb", "on": True},
    "tables": {"iv": {"data": {"voltage": list(range(PAGE * 3 + 5))}}},
    "error": None,
}


def child(model, parent, key):
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        if model.data(index) == key:
            return index
    raise KeyError(key)


def test_lines_show_keys_previews_and_are_made_when_unfolded(app):
    model = JsonModel(VALUE)
    top = QModelIndex()
    assert model.rowCount(top) == 3
    parameters = child(model, top, "parameters")
    assert model.data(parameters.siblingAtColumn(1)) == "{4}"
    assert model.node(parameters).children is None  # not unfolded yet
    note = child(model, parameters, "note")
    assert model.data(note.siblingAtColumn(1)) == '"a ⏎ b"'
    assert model.data(child(model, parameters, "on").siblingAtColumn(1)) == "true"
    assert model.data(child(model, top, "error").siblingAtColumn(1)) == "null"
    assert not model.hasChildren(child(model, top, "error"))


def test_a_long_array_comes_in_pages(app):
    model = JsonModel(VALUE)
    voltage = child(
        model, child(model, child(model, child(model, QModelIndex(), "tables"),
                                  "iv"), "data"), "voltage",
    )  # fmt: skip
    assert model.data(voltage.siblingAtColumn(1)) == f"[{PAGE * 3 + 5}]"
    assert model.rowCount(voltage) == 4
    last = model.index(3, 0, voltage)
    assert model.data(last) == f"[{PAGE * 3} … {PAGE * 3 + 4}]"
    assert model.rowCount(last) == 5
    item = model.node(model.index(2, 0, last))
    assert item.value == PAGE * 3 + 2
    assert item.path() == ("tables", "iv", "data", "voltage", PAGE * 3 + 2)
    assert dotted(item.path()) == f"tables.iv.data.voltage[{PAGE * 3 + 2}]"
    assert page_size(PAGE) == 1 and page_size(PAGE + 1) == PAGE
    assert page_size(PAGE * PAGE + 1) == PAGE * PAGE


def test_the_view_unfolds_a_level_at_a_time_and_copies(app):
    view = JsonView(VALUE)
    tree, model = view.tree, view.model()
    parameters = child(model, QModelIndex(), "parameters")
    tables = child(model, QModelIndex(), "tables")
    assert tree.isExpanded(parameters) and tree.isExpanded(tables)
    iv = child(model, tables, "iv")
    assert not tree.isExpanded(iv)
    view.unfold()
    assert tree.isExpanded(iv)
    tree.setCurrentIndex(parameters)
    view.copy()
    assert json.loads(QGuiApplication.clipboard().text()) == VALUE["parameters"]
    view.copy_path()
    assert QGuiApplication.clipboard().text() == "parameters"
    view.fold()
    assert not tree.isExpanded(parameters)
