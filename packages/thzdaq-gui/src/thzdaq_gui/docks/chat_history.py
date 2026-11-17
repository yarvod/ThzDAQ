"""The chats the assistant keeps, a page of its dock: a search by title over
the chats of the window's workspace for the mode shown, the newest first,
each with how long ago it was spoken in last. A click (or Enter) opens one;
F2 or its menu renames it in place. A view of AssistantModel."""

import time
from typing import List, Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.chat import Kept
from thzdaq_gui.models.assistant import AssistantModel, ago

SEARCH = "Search by title"
NONE_KEPT = "No chats in this workspace yet"
NONE_FOUND = "No chat's title holds that"
ID = Qt.UserRole  # of a row: its chat's id


class HistoryPage(QWidget):
    chosen = Signal(str)  # the id of a chat to open

    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.search = QLineEdit()
        self.search.setPlaceholderText(SEARCH)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.show_chats)
        self.list = QTreeWidget()
        self.list.setColumnCount(2)
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setEditTriggers(QAbstractItemView.EditKeyPressed)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.list.itemClicked.connect(self._open)
        self.list.itemActivated.connect(self._open)
        self.list.itemChanged.connect(self._renamed)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color: {theme.MUTED};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.empty, 1)
        model.history_changed.connect(self.show_chats)
        model.mode_changed.connect(self.show_chats)
        self.show_chats()

    def ids(self) -> List[str]:
        """Of the rows shown, in order."""
        return [
            self.list.topLevelItem(row).data(0, ID)
            for row in range(self.list.topLevelItemCount())
        ]

    def show_chats(self) -> None:
        """The chats listed whose title holds what is searched, the one shown
        in bold. The same chats shown already change in place, so a row
        edited stays."""
        chats = self.model.chats(self.search.text())
        now, current = time.time(), self.model.current_chat()
        if [chat.id for chat in chats] == self.ids():
            for row, chat in enumerate(chats):
                self._show(self.list.topLevelItem(row), chat, now, current)
            return
        rows = []
        for chat in chats:
            item = QTreeWidgetItem()
            item.setData(0, ID, chat.id)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            item.setForeground(1, QColor(theme.MUTED))
            self._show(item, chat, now, current)
            rows.append(item)
        self.list.clear()
        self.list.addTopLevelItems(rows)
        self.list.setVisible(bool(rows))
        self.empty.setText(NONE_FOUND if self.search.text().strip() else NONE_KEPT)
        self.empty.setVisible(not rows)

    @staticmethod
    def _show(
        item: QTreeWidgetItem, chat: Kept, now: float, current: Optional[str]
    ) -> None:
        item.setText(0, chat.title)
        item.setText(1, ago(chat.updated, now))
        font = item.font(0)
        font.setBold(chat.id == current)
        item.setFont(0, font)

    def rename(self, item: QTreeWidgetItem) -> None:
        """Edit its title in place."""
        self.list.setCurrentItem(item)
        self.list.editItem(item, 0)

    def _open(self, item: QTreeWidgetItem) -> None:
        self.chosen.emit(item.data(0, ID))

    def _renamed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self.model.rename_chat(item.data(0, ID), item.text(0))

    def _menu(self, at: QPoint) -> None:
        item = self.list.itemAt(at)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction(
            theme.icon("folder-open-outline"), "Open", lambda: self._open(item)
        )
        menu.addAction(
            theme.icon("pencil-outline"), "Rename", lambda: self.rename(item)
        )
        menu.exec(self.list.viewport().mapToGlobal(at))
