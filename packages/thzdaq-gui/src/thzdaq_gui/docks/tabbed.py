"""A bottom dock of tabs of its own (Editor: a tab per file open), plain Qt
tabs inside one dock, as an editor has them: the close button of a tab or a
middle click closes it (its owner may say no: unsaved work), tabs are moved
by dragging, and with no tab the dock shows what to start with.

The owner (CodeDocks) makes the widgets of the tabs, names them and decides
whether one closes; this only shows them.
"""

from typing import Callable, List, Sequence, Tuple

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme

# What the dock starts with: (text, icon, slot), on its empty page and in the
# menu of the + at the end of its tabs
Start = Tuple[str, str, Callable[[], None]]
EMPTY, TABS = 0, 1  # pages


class TabbedDock(QStackedWidget):
    closed = Signal(object)  # the widget of a tab that closed (deleted next)
    current_changed = Signal(object)  # the widget of the current tab, or None

    def __init__(
        self,
        hint: str,
        starts: Sequence[Start],
        closing: Callable[[QWidget], bool],
        parent=None,
    ):
        """hint: said while no tab is open; closing(widget): whether its tab
        closes now (asked by its close button and a middle click)."""
        super().__init__(parent)
        self.closing = closing
        self.addWidget(self._empty(hint, starts))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().installEventFilter(self)
        self.tabs.currentChanged.connect(
            lambda index: self.current_changed.emit(self.tabs.widget(index))
        )
        self.tabs.setCornerWidget(self._more(starts), Qt.TopRightCorner)
        self.addWidget(self.tabs)

    def _empty(self, hint: str, starts: Sequence[Start]) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.addStretch()
        label = QLabel(hint)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color: {theme.MUTED};")
        column.addWidget(label)
        for text, icon, slot in starts:
            button = QPushButton(theme.icon(icon), text)
            button.clicked.connect(slot)
            column.addWidget(button, 0, Qt.AlignHCenter)
        column.addStretch()
        return page

    def _more(self, starts: Sequence[Start]) -> QToolButton:
        button = QToolButton()
        button.setIcon(theme.icon("plus"))
        button.setAutoRaise(True)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        for text, icon, slot in starts:
            menu.addAction(theme.icon(icon), text, slot)
        button.setMenu(menu)
        return button

    # The tabs
    def widgets(self) -> List[QWidget]:
        """In the order of the tabs."""
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def add(self, widget: QWidget, title: str, tip: str = "", icon=None) -> None:
        index = self.tabs.addTab(widget, title)
        self.tabs.setTabToolTip(index, tip)
        if icon is not None:
            self.tabs.setTabIcon(index, icon)
        # The close button of the theme, as on the tabs of the docks; the bar
        # its parent from the start: PySide keeps no button set on a tab alive
        close = QToolButton(self.tabs.tabBar())
        close.setIcon(theme.icon("close"))
        close.setAutoRaise(True)
        close.setToolTip("Close")
        close.clicked.connect(lambda: self.request_close(widget))
        self.tabs.tabBar().setTabButton(index, QTabBar.RightSide, close)
        self.setCurrentIndex(TABS)

    def show_tab(self, widget: QWidget) -> None:
        """Its tab the current one."""
        self.tabs.setCurrentWidget(widget)

    def current(self) -> QWidget:
        return self.tabs.currentWidget()

    def title(self, widget: QWidget) -> str:
        return self.tabs.tabText(self.tabs.indexOf(widget))

    def retitle(self, widget: QWidget, title: str) -> None:
        index = self.tabs.indexOf(widget)
        if index >= 0:
            self.tabs.setTabText(index, title)

    def request_close(self, widget: QWidget) -> bool:
        """As its close button does: closed if its owner says so."""
        index = self.tabs.indexOf(widget)
        return index >= 0 and self._close_at(index)

    def _close_at(self, index: int) -> bool:
        widget = self.tabs.widget(index)
        if not self.closing(widget):
            return False
        self.tabs.removeTab(self.tabs.indexOf(widget))
        self.closed.emit(widget)
        widget.deleteLater()
        if self.tabs.count() == 0:
            self.setCurrentIndex(EMPTY)
        return True

    def eventFilter(self, watched, event) -> bool:
        """A middle click on a tab closes it."""
        if (
            watched is self.tabs.tabBar()
            and event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.MiddleButton
        ):
            index = self.tabs.tabBar().tabAt(event.position().toPoint())
            if index >= 0:
                self._close_at(index)
                return True
        return super().eventFilter(watched, event)
