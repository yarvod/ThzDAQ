"""A JSON value as a tree that folds, as an editor shows JSON: an object's keys
and an array's items under it, each folded to a preview ({3}, [120]); a long
array in pages of PAGE items ([0 … 99]), pages of pages when it is longer
still. Children are made when their parent is first unfolded, so a
measurement's long tables cost nothing until looked at.

JsonView is the tree with its bar: unfold a level more, fold all, copy what is
selected (its value as JSON, or its path), copy the whole value."""

import json
from typing import Any, List, Optional, Sequence, Tuple, Union

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme

PAGE = 100  # items of an array shown at once
SHOWN = 200  # letters of a string its line shows
TIP = 2000  # letters of a long string its tooltip shows
KEY, VALUE = range(2)
STRING_COLOR = "#a5d6a7"
NUMBER_COLOR = "#90caf9"

Key = Union[str, int]


class Node:
    """A value in the tree, or a page of an array (its items start..stop)."""

    __slots__ = ("key", "value", "parent", "row", "page", "children")

    def __init__(
        self,
        key: Key,
        value: Any,
        parent: Optional["Node"],
        row: int,
        page: Optional[Tuple[int, int]] = None,
    ):
        self.key, self.value, self.parent, self.row = key, value, parent, row
        self.page = page  # (start, stop) of a page of value, an array
        self.children: Optional[List[Node]] = None  # made when first asked

    def folds(self) -> bool:
        return self.page is not None or (
            isinstance(self.value, (dict, list)) and bool(self.value)
        )

    def kids(self) -> List["Node"]:
        if self.children is None:
            self.children = self._made()
        return self.children

    def _made(self) -> List["Node"]:
        if isinstance(self.value, dict) and self.page is None:
            return [
                Node(key, value, self, row)
                for row, (key, value) in enumerate(self.value.items())
            ]
        start, stop = self.page or (0, len(self.value))
        size = page_size(stop - start)
        if size == 1:
            return [
                Node(index, self.value[index], self, row)
                for row, index in enumerate(range(start, stop))
            ]
        return [
            Node(f"[{first} … {min(first + size, stop) - 1}]", self.value, self, row,
                 (first, min(first + size, stop)))
            for row, first in enumerate(range(start, stop, size))
        ]  # fmt: skip

    def path(self) -> Tuple[Key, ...]:
        """Keys and indices from the top; pages are not in it."""
        if self.parent is None:
            return ()
        above = self.parent.path()
        return above if self.page is not None else above + (self.key,)

    def shown(self) -> Any:
        """What copying it gives: its value, or the items of its page."""
        if self.page is not None:
            return self.value[self.page[0] : self.page[1]]
        return self.value


def page_size(count: int) -> int:
    """Items in each page so that no level has more than PAGE lines: 1 (no
    pages) up to PAGE items, then PAGE, PAGE², ..."""
    size = 1
    while count > size * PAGE:
        size *= PAGE
    return size


def preview(node: Node) -> str:
    """Its value in a line: a folded object or array by its size."""
    value = node.value
    if node.page is not None:
        return f"{node.page[1] - node.page[0]} items"
    if isinstance(value, dict):
        return f"{{{len(value)}}}" if value else "{}"
    if isinstance(value, list):
        return f"[{len(value)}]" if value else "[]"
    if isinstance(value, str):
        line = value.replace("\n", " ⏎ ")
        cut = line if len(line) <= SHOWN else line[: SHOWN - 1] + "…"
        return f'"{cut}"'
    return json.dumps(value, ensure_ascii=False)


def color(node: Node) -> str:
    value = node.value
    if node.page is not None or isinstance(value, (dict, list)):
        return theme.MUTED
    if isinstance(value, str):
        return STRING_COLOR
    if isinstance(value, bool) or value is None:
        return theme.ACCENT
    return NUMBER_COLOR


class JsonModel(QAbstractItemModel):
    """A JSON value (dicts, lists, strings, numbers, bools, None) as rows."""

    def __init__(self, value: Any, parent=None):
        super().__init__(parent)
        self.value = value
        self.root = Node("", value, None, 0)

    def node(self, index: QModelIndex) -> Node:
        return index.internalPointer() if index.isValid() else self.root

    def value_at(self, path: Sequence[Key]) -> Any:
        """The value at a path of keys and indices (as Node.path gives)."""
        found = self.value
        for key in path:
            found = found[key]
        return found

    # Qt model
    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        kids = self.node(parent).kids()
        if 0 <= row < len(kids):
            return self.createIndex(row, column, kids[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        above = index.internalPointer().parent
        if above is None or above is self.root:
            return QModelIndex()
        return self.createIndex(above.row, 0, above)

    def hasChildren(self, parent=QModelIndex()) -> bool:
        return self.node(parent).folds()

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        node = self.node(parent)
        return len(node.kids()) if node.folds() else 0

    def columnCount(self, parent=QModelIndex()) -> int:
        return 2

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return ("Key", "Value")[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == Qt.DisplayRole:
            return str(node.key) if index.column() == KEY else preview(node)
        if role == Qt.ForegroundRole:
            if index.column() == VALUE:
                return QColor(color(node))
            if isinstance(node.key, int) or node.page is not None:
                return QColor(theme.MUTED)
        if role == Qt.ToolTipRole and index.column() == VALUE:
            if isinstance(node.value, str) and len(node.value) > SHOWN:
                return node.value[:TIP]
        return None


class JsonView(QWidget):
    """The tree of a JSON value with its bar; the top level unfolded."""

    def __init__(self, value: Any, parent=None):
        super().__init__(parent)
        self.tree = QTreeView()
        self.tree.setModel(JsonModel(value, self))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.menu)
        header = self.tree.header()
        header.setSectionResizeMode(KEY, QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.tree.setColumnWidth(KEY, 220)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        for text, icon, tip, slot in (
            ("Unfold", "unfold-more-horizontal", "Unfold one level more", self.unfold),
            ("Fold all", "unfold-less-horizontal", "Fold everything", self.fold),
            ("Copy", "content-copy", "Copy what is selected as JSON", self.copy),
            ("Copy all", "code-json", "Copy the whole value as JSON", self.copy_all),
        ):
            bar.addWidget(theme.tool_button(text, icon, tip, slot))
        bar.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.tree)
        self.unfold()

    def model(self) -> JsonModel:
        return self.tree.model()

    def unfold(self) -> None:
        """Unfold every folded line under those unfolded, pages excepted:
        one level more."""
        model = self.model()
        folded: List[QModelIndex] = []

        def walk(parent: QModelIndex) -> None:
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                if not model.hasChildren(index) or model.node(index).page:
                    continue
                if self.tree.isExpanded(index):
                    walk(index)
                else:
                    folded.append(index)

        walk(QModelIndex())
        for index in folded:
            self.tree.expand(index)

    def fold(self) -> None:
        self.tree.collapseAll()

    def selected(self) -> List[Node]:
        model = self.model()
        return [
            model.node(index) for index in self.tree.selectionModel().selectedRows()
        ]

    def copy(self) -> None:
        nodes = self.selected()
        if not nodes:
            return
        values = [node.shown() for node in nodes]
        clip(values[0] if len(values) == 1 else values)

    def copy_path(self) -> None:
        nodes = self.selected()
        if nodes:
            QGuiApplication.clipboard().setText(
                "\n".join(dotted(node.path()) for node in nodes)
            )

    def copy_all(self) -> None:
        clip(self.model().value)

    def menu(self, at) -> None:
        if not self.selected():
            return
        menu = QMenu(self)
        menu.addAction(theme.icon("content-copy"), "Copy value", self.copy)
        menu.addAction(theme.icon("map-marker-path"), "Copy path", self.copy_path)
        menu.exec(self.tree.viewport().mapToGlobal(at))


def clip(value: Any) -> None:
    QGuiApplication.clipboard().setText(json.dumps(value, indent=2, ensure_ascii=False))


def dotted(path: Sequence[Key]) -> str:
    """tables.iv.data.voltage[3]"""
    text = ""
    for key in path:
        text += f"[{key}]" if isinstance(key, int) else (f".{key}" if text else key)
    return text
