"""The docks of the window by name: where they open and what state they are in.

DockSpace holds every ADS dock of the window under its name (dock_names) and
places it: a closed dock opens with its kind (graphs with graphs, devices
with devices) or on its home side, a base dock on its side bar. DockBody
contents exist only while their docks are open (sync_bodies).
"""

from collections import Counter
from contextlib import contextmanager
from typing import Dict, Iterator, List, Mapping, Optional, Sequence

import PySide6QtAds as QtAds
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSplitter, QStyle, QWidget

from thzdaq_gui import theme
from thzdaq_gui.dock_names import (
    DATA,
    DEVICE,
    GRAPH,
    LOG,
    MEASURE,
    MEASUREMENT,
    PROCESSES,
    SETUP,
    kind_of,
)
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.graphs import close_views
from thzdaq_gui.navigator import BEHIND, CLOSED, FRONT, DockEntry, Flash

SECTIONS = ("Base", "Devices", "Measures", "Graphs")  # of the menus, in order
AUTO_HIDE_SIZES = {SETUP: 460, DATA: 640, LOG: 260, PROCESSES: 220}
FIT_SHARE = 0.4  # a dock opened on its side takes at most this part of the window
# Where a dock of each kind opens when no dock of its kind is on screen
HOME_AREAS = {
    GRAPH: QtAds.CenterDockWidgetArea,
    MEASURE: QtAds.RightDockWidgetArea,
    MEASUREMENT: QtAds.RightDockWidgetArea,
    DEVICE: QtAds.BottomDockWidgetArea,
}


def configure_docking() -> None:
    """Global ADS flags; must run before the first CDockManager exists."""
    manager = QtAds.CDockManager
    manager.setConfigFlag(manager.FocusHighlighting, True)
    manager.setConfigFlag(manager.OpaqueSplitterResize, True)
    manager.setConfigFlag(manager.DockAreaHasTabsMenuButton, True)
    manager.setConfigFlag(manager.FloatingContainerHasWidgetIcon, True)
    manager.setConfigFlag(manager.AllTabsHaveCloseButton, True)
    # The close button of a tab group closes its current tab, not the whole group
    manager.setConfigFlag(manager.DockAreaCloseButtonClosesTab, True)
    manager.setAutoHideConfigFlags(QtAds.CDockManager.DefaultAutoHideConfig)
    provider = manager.iconProvider()
    for which, name in (
        (QtAds.TabCloseIcon, "close"),
        (QtAds.DockAreaCloseIcon, "close"),
        (QtAds.DockAreaMenuIcon, "chevron-down"),
        (QtAds.DockAreaUndockIcon, "dock-window"),
        (QtAds.DockAreaMinimizeIcon, "window-minimize"),
        (QtAds.AutoHideIcon, "pin-outline"),
    ):
        provider.registerCustomIcon(which, theme.icon(name))


@contextmanager
def one_repaint(window: QWidget) -> Iterator[None]:
    """A wait cursor and one repaint for a new layout instead of every step
    of the rebuild."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    window.setUpdatesEnabled(False)
    try:
        yield
    finally:
        window.setUpdatesEnabled(True)
        QApplication.restoreOverrideCursor()


class DockSpace(Mapping):
    """The docks by name (a read-only mapping); add() and remove() change it."""

    def __init__(self, manager: QtAds.CDockManager):
        self.manager = manager
        self._docks: Dict[str, QtAds.CDockWidget] = {}
        self.entries: Dict[str, DockEntry] = {}  # in the menus and Ctrl+K
        self.auto_hide_sides: Dict[str, int] = {}  # base docks: their side bar
        # Docks are added open and then arranged: contents are built after that
        self.building = False

    def __getitem__(self, name: str) -> QtAds.CDockWidget:
        return self._docks[name]

    def __iter__(self):
        return iter(self._docks)

    def __len__(self) -> int:
        return len(self._docks)

    def add(
        self,
        name: str,
        title: str,
        widget,
        section: str,
        icon=None,
        area=None,
        auto_hide=None,
        group: str = "",
        hint: str = "",
        listed: bool = True,
    ) -> QtAds.CDockWidget:
        dock = QtAds.CDockWidget(name)
        dock.setWindowTitle(title)
        dock.setWidget(widget)
        if icon is not None:
            dock.setIcon(icon)
        dock.setFeature(QtAds.CDockWidget.DockWidgetDeleteOnClose, False)
        dock.toggleViewAction().setText(title)
        if listed:
            self.entries[name] = DockEntry(
                name, title, section, icon or theme.icon("dock-window"), group, hint
            )
        if isinstance(widget, DockBody):
            dock.viewToggled.connect(
                lambda on, body=widget: self.building or body.set_open(on)
            )
        if auto_hide is not None:
            self.auto_hide_sides[name] = auto_hide
            container = self.manager.addAutoHideDockWidget(auto_hide, dock)
            container.setSize(AUTO_HIDE_SIZES.get(name, 420))
        else:
            self.manager.addDockWidgetTab(area or QtAds.CenterDockWidgetArea, dock)
        self._docks[name] = dock
        if isinstance(widget, DockBody) and not self.building:
            widget.set_open(not dock.isClosed())
        return dock

    def remove(self, name: str) -> None:
        dock = self._docks.pop(name, None)
        if dock is None:
            return
        widget = dock.widget()
        if isinstance(widget, DockBody):
            widget.dispose()
        elif hasattr(widget, "stop"):
            widget.stop()
        if widget is not None:
            close_views(widget)
        self.entries.pop(name, None)
        self.manager.removeDockWidget(dock)
        dock.deleteLater()

    def retitle(self, name: str, title: str) -> None:
        """On its tab, its toolbar button and in the menus."""
        dock = self._docks[name]
        dock.setWindowTitle(title)
        dock.toggleViewAction().setText(title)
        if name in self.entries:
            self.entries[name].title = title

    def sync_bodies(self) -> None:
        """Content only in open docks (after a layout or perspective is restored)."""
        for dock in self._docks.values():
            body = dock.widget()
            if isinstance(body, DockBody):
                body.set_open(not dock.isClosed())

    def listed(self) -> List[DockEntry]:
        """The docks of the menus and Ctrl+K, by section."""
        entries = [self.entries[name] for name in self._docks if name in self.entries]
        return sorted(entries, key=lambda e: SECTIONS.index(e.section))

    def state(self, name: Optional[str]) -> str:
        """CLOSED, BEHIND another tab or in FRONT."""
        dock = self._docks.get(name) if name else None
        if dock is None or dock.isClosed():
            return CLOSED
        if dock.isAutoHide():
            container = dock.autoHideDockContainer()
            return FRONT if container is not None and container.isVisible() else BEHIND
        return FRONT if dock.isCurrentTab() else BEHIND

    def show(self, name: str) -> None:
        """Wherever the dock is, bring it in front of the user and flash it."""
        dock = self._docks.get(name)
        if dock is None:
            return
        self.open(name)
        window = dock.window()
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()
        self.manager.setDockWidgetFocused(dock)
        Flash(dock)

    def toggle(self, name: str) -> None:
        dock = self._docks.get(name)
        if dock is None:
            return
        if dock.isClosed():
            self.open(name)
        else:
            dock.toggleView(False)
            self.sync_bodies()

    def open(self, name: str, activate: bool = True) -> None:
        """Show a dock where its kind is: a closed one joins the tab group of
        an open dock of the same kind (graphs with graphs, devices with
        devices), or opens on its side; activate brings it to the front."""
        dock = self._docks.get(name)
        if dock is None:
            return
        if dock.isClosed():
            own = dock.dockAreaWidget()
            move = own is None or own.openDockWidgetsCount() == 0
            side = self.auto_hide_sides.get(name)
            if (
                own is None
                and dock.autoHideDockContainer() is None
                and side is not None
            ):
                # Not in a layout saved before this dock existed: ADS would
                # float it; back to its side bar
                container = self.manager.addAutoHideDockWidget(side, dock)
                container.setSize(AUTO_HIDE_SIZES.get(name, 420))
                move = False
            # Open before moving: ADS keeps the tab of a closed dock it moves
            # into a new area hidden, and the content is built by now
            dock.toggleView(True)
            if move:
                kind = kind_of(name)
                area = self.open_area_of(kind, dock)
                if area is not None:
                    self.manager.addDockWidgetTabToArea(dock, area)
                elif kind in HOME_AREAS:
                    area = self.manager.addDockWidget(HOME_AREAS[kind], dock)
                    self.fit(area, dock)
            activate = True  # a dock just opened is the one to see
        if activate:
            dock.setAsCurrentTab()
            dock.raise_()
            if dock.isAutoHide() and dock.autoHideDockContainer() is not None:
                dock.autoHideDockContainer().collapseView(False)
        self.sync_bodies()

    def fit(self, area, dock) -> None:
        """A new area on a side as wide (or tall) as its dock wants, up to
        FIT_SHARE of the window: ADS sizes it before the content exists."""
        splitter = area.parentWidget() if area is not None else None
        if not isinstance(splitter, QSplitter):
            return
        index, sizes = splitter.indexOf(area), splitter.sizes()
        if index < 0 or len(sizes) < 2:
            return
        horizontal = splitter.orientation() == Qt.Horizontal
        hint = dock.widget().sizeHint()
        wanted = (
            hint.width() if horizontal else hint.height()
        ) + dock.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        wanted = min(wanted, int(sum(sizes) * FIT_SHARE))
        if sizes[index] >= wanted:
            return
        # Taken from the largest neighbour (the graphs)
        other = max((i for i in range(len(sizes)) if i != index), key=sizes.__getitem__)
        sizes[other] -= wanted - sizes[index]
        sizes[index] = wanted
        splitter.setSizes(sizes)

    def areas_of(self, kind: str) -> list:
        """Tab groups in the window holding open docks of this kind."""
        return list(dict.fromkeys(self._docked(kind)))

    def open_area_of(self, kind: str, besides=None):
        """The tab group holding the most open docks of this kind (not floating)."""
        counts = Counter(self._docked(kind, besides))
        return counts.most_common(1)[0][0] if counts else None

    def _docked(self, kind: str, besides=None):
        """The tab group of every open dock of a kind that is neither floating
        nor on a side bar."""
        for name, dock in self._docks.items():
            if dock is besides or dock.isClosed() or kind_of(name) != kind:
                continue
            area = dock.dockAreaWidget()
            if area is None or dock.isFloating() or dock.isAutoHide():
                continue
            yield area

    # Default layouts
    def close_kinds(self, *kinds: str) -> None:
        for name, dock in self._docks.items():
            if kind_of(name) in kinds:
                dock.toggleView(False)

    def tab_group(self, side, names: Sequence[str], beside=None):
        """These docks as the tabs of one new group on a side of the window
        (or of the group `beside`); the group, None without any of them."""
        group = None
        for name in names:
            dock = self._docks.get(name)
            if dock is None:
                continue
            dock.toggleView(True)  # first: see open()
            if group is None:
                group = self.manager.addDockWidget(side, dock, beside)
            else:
                self.manager.addDockWidgetTabToArea(dock, group)
        return group
