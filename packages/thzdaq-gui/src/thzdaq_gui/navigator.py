"""Finding docks: menus with a search field and a tree by type, and Ctrl+K.

A row shows a dock: a click opens it, brings it to the front and flashes its
frame, wherever it is (behind a tab, folded into a side bar, floating). The
eye on the right only opens or closes it. Docks of one type (four SIS biases,
five power supplies) share a branch; a type with one dock stays a plain row.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QLineEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from thzdaq_gui import theme

FRONT, BEHIND, CLOSED = "front", "behind", "closed"
EXPANDED_KEY = "navigator/expanded"
NAME_ROLE = Qt.UserRole
GROUP_ROLE = Qt.UserRole + 1
MAX_ROWS = 20
FLASH_MS = 700

# Words of type keys written in capitals ("sis_bias" -> "SIS bias")
ACRONYMS = {"sis", "vna", "yig", "if", "lo", "rf", "nrx", "pid", "2sb"}


def type_title(key: str) -> str:
    words = [w.upper() if w in ACRONYMS else w for w in key.split("_") if w]
    if not words:
        return key
    first = words[0]
    return " ".join([first[:1].upper() + first[1:], *words[1:]])


def instrument_type(instrument_id: str) -> str:
    """power_supply_3 -> power_supply: profile ids name the kind of device."""
    return re.sub(r"_\d+$", "", instrument_id)


@dataclass
class DockEntry:
    name: str
    title: str
    section: str  # the menu: Base, Devices, Measures, Graphs
    icon: QIcon = field(default_factory=QIcon)
    group: str = ""  # type of the device, group of the procedure
    hint: str = ""  # more text to search: ref, procedure name

    def where(self) -> str:
        return f"{self.section} › {self.group}" if self.group else self.section

    def matches(self, words: Sequence[str]) -> bool:
        text = f"{self.title} {self.group} {self.section} {self.hint}".lower()
        return all(word in text for word in words)

    def rank(self, words: Sequence[str]) -> int:
        """Lower first: the title itself, then titles starting with the search."""
        title, query = self.title.lower(), " ".join(words)
        if title == query:
            return 0
        if title.startswith(query):
            return 1
        return 2 if query in title else 3


class DockNavigator(QWidget):
    """Search field and the tree of docks of some sections (all of them for Ctrl+K)."""

    activated = Signal(str)  # a dock was brought to the front

    def __init__(
        self,
        entries: Callable[[], List[DockEntry]],
        state: Callable[[str], str],
        show: Callable[[str], None],
        toggle: Callable[[str], None],
        sections: Optional[Sequence[str]] = None,
        settings=None,
        parent=None,
    ):
        super().__init__(parent)
        self._entries = entries
        self._state = state
        self._show = show
        self._toggle = toggle
        self.sections = tuple(sections) if sections else None
        self.settings = settings
        self.expanded = set(self._load_expanded())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(
            theme.icon("magnify", theme.MUTED), QLineEdit.LeadingPosition
        )
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setMouseTracking(True)
        # A soft selection: the keyboard row, not a choice already made
        self.tree.setStyleSheet(
            "QTreeView { selection-background-color: #4a3a1c; "
            f"selection-color: {theme.TEXT}; }}"
        )
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.resizeSection(2, 26)
        self.tree.itemClicked.connect(self.clicked)
        self.tree.itemActivated.connect(lambda item, _: self.activate(item))
        self.tree.itemExpanded.connect(lambda item: self.remember(item, True))
        self.tree.itemCollapsed.connect(lambda item: self.remember(item, False))
        layout.addWidget(self.tree)
        self.setMinimumWidth(340)

    # Entries and rows
    def entries(self) -> List[DockEntry]:
        return [
            e
            for e in self._entries()
            if self.sections is None or e.section in self.sections
        ]

    def refresh(self, *_) -> None:
        words = self.search.text().lower().split()
        self.tree.clear()
        entries = self.entries()
        if words:
            found = [e for e in entries if e.matches(words)]
            for entry in sorted(found, key=lambda e: e.rank(words)):
                self.tree.addTopLevelItem(self.entry_item(entry, where=True))
        else:
            sections = list(dict.fromkeys(e.section for e in entries))
            for section in sections:
                own = [e for e in entries if e.section == section]
                if self.sections is not None and len(self.sections) == 1:
                    parent = None
                else:
                    parent = QTreeWidgetItem([section])
                    font = QFont(parent.font(0))
                    font.setBold(True)
                    parent.setFont(0, font)
                    parent.setForeground(0, QColor(theme.ACCENT))
                    parent.setFlags(Qt.ItemIsEnabled)
                    self.tree.addTopLevelItem(parent)
                    parent.setExpanded(True)
                self.add_grouped(own, parent)
        self.tree.setColumnHidden(1, not words)
        # Enter takes the best match while searching
        if words:
            self.select_first()
        else:
            self.tree.setCurrentItem(None)
        self.fit()

    def add_grouped(self, entries: List[DockEntry], parent) -> None:
        counts: Dict[str, int] = {}
        for entry in entries:
            if entry.group:
                counts[entry.group] = counts.get(entry.group, 0) + 1
        groups: Dict[str, QTreeWidgetItem] = {}
        add = parent.addChild if parent is not None else self.tree.addTopLevelItem
        for entry in entries:
            if counts.get(entry.group, 0) < 2:
                add(self.entry_item(entry))
                continue
            group = groups.get(entry.group)
            if group is None:
                group = QTreeWidgetItem([f"{entry.group}  ({counts[entry.group]})"])
                group.setIcon(0, entry.icon)
                group.setData(0, GROUP_ROLE, f"{entry.section}/{entry.group}")
                group.setFlags(Qt.ItemIsEnabled)
                add(group)
                groups[entry.group] = group
            group.addChild(self.entry_item(entry))
        for group in groups.values():
            group.setExpanded(group.data(0, GROUP_ROLE) in self.expanded)

    def entry_item(self, entry: DockEntry, where: bool = False) -> QTreeWidgetItem:
        item = QTreeWidgetItem([entry.title, entry.where() if where else "", ""])
        item.setIcon(0, entry.icon)
        item.setData(0, NAME_ROLE, entry.name)
        item.setToolTip(0, f"{entry.title} · {entry.where()}\nClick to show it")
        item.setForeground(1, QColor(theme.MUTED))
        self.show_state(item)
        return item

    def show_state(self, item: QTreeWidgetItem) -> None:
        name = item.data(0, NAME_ROLE)
        state = self._state(name)
        icon_name, color, tip = {
            FRONT: ("eye", theme.ACCENT, "On screen: click to close"),
            BEHIND: ("eye", theme.TEXT, "Open behind another dock: click to close"),
            CLOSED: ("eye-off-outline", theme.MUTED, "Closed: click to open"),
        }[state]
        item.setIcon(2, theme.icon(icon_name, color))
        item.setToolTip(2, tip)
        item.setForeground(0, QColor(theme.TEXT if state != CLOSED else theme.MUTED))

    def items(self) -> List[QTreeWidgetItem]:
        found = []

        def walk(item):
            if item.data(0, NAME_ROLE):
                found.append(item)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return found

    def item(self, name: str) -> Optional[QTreeWidgetItem]:
        return next((i for i in self.items() if i.data(0, NAME_ROLE) == name), None)

    def update_states(self) -> None:
        for item in self.items():
            self.show_state(item)

    def select_first(self) -> None:
        visible = self.visible_items()
        self.tree.setCurrentItem(visible[0] if visible else None)

    def visible_items(self) -> List[QTreeWidgetItem]:
        result = []
        item = self.tree.topLevelItem(0)
        while item is not None:
            if item.data(0, NAME_ROLE):
                result.append(item)
            item = self.tree.itemBelow(item)
        return result

    def fit(self) -> None:
        """Tall enough for the open rows, up to MAX_ROWS."""
        rows, item = 0, self.tree.topLevelItem(0)
        while item is not None:
            rows += 1
            item = self.tree.itemBelow(item)
        row = self.tree.sizeHintForRow(0) if rows else 22
        frame = 2 * self.tree.frameWidth()
        self.tree.setFixedHeight(max(3, min(rows, MAX_ROWS)) * max(row, 18) + frame + 2)
        self.adjustSize()
        host = self.parentWidget()
        if isinstance(host, QMenu):
            # A menu measures a widget action again only when the action changes
            for action in host.actions():
                if isinstance(action, QWidgetAction) and action.defaultWidget() is self:
                    action.setStatusTip("" if action.statusTip() else " ")
        elif isinstance(host, QuickFind):
            host.adjustSize()

    # Clicks
    def clicked(self, item: QTreeWidgetItem, column: int) -> None:
        name = item.data(0, NAME_ROLE)
        if not name:
            if item.data(0, GROUP_ROLE):
                item.setExpanded(not item.isExpanded())
            return
        if column == 2:
            self._toggle(name)
            self.update_states()
        else:
            self.activate(item)

    def activate(self, item: Optional[QTreeWidgetItem]) -> None:
        name = item.data(0, NAME_ROLE) if item is not None else None
        if not name:
            if item is not None and item.data(0, GROUP_ROLE):
                item.setExpanded(not item.isExpanded())
            return
        self._show(name)
        self.update_states()
        self.activated.emit(name)

    def remember(self, item: QTreeWidgetItem, expanded: bool) -> None:
        key = item.data(0, GROUP_ROLE)
        if not key:
            return
        (self.expanded.add if expanded else self.expanded.discard)(key)
        if self.settings is not None:
            self.settings.setValue(EXPANDED_KEY, json.dumps(sorted(self.expanded)))
        self.fit()

    def _load_expanded(self) -> List[str]:
        if self.settings is None:
            return []
        try:
            return list(json.loads(self.settings.value(EXPANDED_KEY) or "[]"))
        except (TypeError, ValueError):
            return []

    def prepare(self) -> None:
        """Before showing: a fresh tree, an empty search with the focus."""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.expanded = set(self._load_expanded())
        self.refresh()
        QTimer.singleShot(0, self.search.setFocus)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                self.tree.setFocus()
                if self.tree.currentItem() is None:
                    self.select_first()
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.activate(self.tree.currentItem())
                return True
        return super().eventFilter(watched, event)


class QuickFind(QFrame):
    """Ctrl+K: a popup over the window with every dock to find."""

    def __init__(self, navigator: DockNavigator, parent: QWidget):
        super().__init__(parent, Qt.Popup)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("quickFind")
        self.setStyleSheet(
            f"#quickFind {{ background: {theme.PANEL}; border: 1px solid {theme.ACCENT}; }}"
        )
        self.navigator = navigator
        navigator.setParent(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(navigator)
        navigator.search.setPlaceholderText("Find a device, measurement or graph…")
        navigator.activated.connect(lambda _: self.hide())
        self.setFixedWidth(460)

    def popup(self) -> None:
        self.navigator.prepare()
        self.adjustSize()
        window = self.parentWidget()
        top = window.mapToGlobal(QPoint(0, 0))
        x = top.x() + (window.width() - self.width()) // 2
        self.move(x, top.y() + 60)
        self.show()
        self.navigator.search.setFocus()


class Flash(QFrame):
    """An accent frame over a dock for a moment: here it is."""

    def __init__(self, target: QWidget):
        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            f"background: transparent; border: 3px solid {theme.ACCENT}; border-radius: 2px;"
        )
        self.setGeometry(target.rect())
        self.raise_()
        self.show()
        QTimer.singleShot(FLASH_MS, self.deleteLater)
