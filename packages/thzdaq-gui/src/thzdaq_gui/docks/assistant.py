"""The assistant's chat: the model server chosen, the messages (each tool call a
folded card: the tool, its arguments, how it went; unfolded, what it
answered), the input and Send / Stop. A view of AssistantModel."""

import json
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.docks.providers import ProvidersDialog
from thzdaq_gui.models.assistant import AssistantModel, Item, Kind, State

PLACEHOLDER = "Ask the assistant (Enter sends, Shift+Enter: a new line)"
STATE_COLORS = {  # of what a call answered
    State.RUNNING: theme.TEXT,
    State.DONE: theme.TEXT,
    State.REFUSED: theme.BAD,
    State.STOPPED: theme.MUTED,
}


class MessageInput(QPlainTextEdit):
    """Enter sends what is typed; Shift+Enter starts a new line."""

    submitted = Signal(str)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if enter and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit(self.toPlainText())
            return
        super().keyPressEvent(event)


def text_label(text: str, markdown: bool = False) -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.MarkdownText if markdown else Qt.PlainText)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setText(text)
    return label


class CallCard(Collapsible):
    """A tool call, folded to its line; unfolded: its arguments and answer."""

    def __init__(self, item: Item, parent=None):
        super().__init__("", expanded=False, parent=parent)
        self.arguments = text_label("")
        self.arguments.setProperty("role", "muted")
        self.answer = text_label("")
        self.addWidget(self.arguments)
        self.addWidget(self.answer)
        self.show_item(item)

    def show_item(self, item: Item) -> None:
        self.setTitle(item.summary())
        self.button.setToolTip(item.state.value)
        self.arguments.setText(json.dumps(item.arguments, ensure_ascii=False))
        self.answer.setText(item.text)
        self.answer.setVisible(bool(item.text))
        self.answer.setStyleSheet(
            f"font-family: monospace; color: {STATE_COLORS[item.state]};"
        )


class Bubble(QFrame):
    """What the person wrote, or what the model answered."""

    def __init__(self, item: Item, parent=None):
        super().__init__(parent)
        self.setObjectName("bubble")
        person = item.kind is Kind.PERSON
        background = theme.PANEL if person else "transparent"
        self.setStyleSheet(
            f"#bubble {{ background: {background}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self.label = text_label(item.text, markdown=not person)
        if item.kind is Kind.NOTE:
            self.label.setProperty("role", "muted")
        layout.addWidget(self.label)

    def show_item(self, item: Item) -> None:
        self.label.setText(item.text)


class AssistantWidget(QWidget):
    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.shown: List[QWidget] = []  # a widget per item of the model

        self.providerBox = QComboBox()
        self.providerBox.setToolTip("The model's server")
        self.providerBox.activated.connect(
            lambda index: model.providers.choose(self.providerBox.itemText(index))
        )
        settings = theme.tool_button("", "cog-outline", "Model servers…", self.edit)
        new = theme.tool_button(
            "New chat", "chat-plus-outline", "Forget this conversation", model.new_chat
        )
        top = QHBoxLayout()
        top.addWidget(self.providerBox, 1)
        top.addWidget(settings)
        top.addWidget(new)

        self.column = QVBoxLayout()
        self.column.setContentsMargins(4, 4, 4, 4)
        self.column.setSpacing(6)
        self.column.addStretch()
        messages = QWidget()
        messages.setLayout(self.column)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(messages)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar = self.scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._grown)
        bar.valueChanged.connect(self._followed)
        self._follow = True  # at the bottom: new messages stay in sight

        self.input = MessageInput()
        self.input.setPlaceholderText(PLACEHOLDER)
        self.input.setFixedHeight(64)
        self.input.submitted.connect(self.send)
        self.sendButton = QToolButton()
        self.sendButton.clicked.connect(self.send_or_stop)
        bottom = QHBoxLayout()
        bottom.addWidget(self.input, 1)
        bottom.addWidget(self.sendButton, 0, Qt.AlignBottom)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.scroll, 1)
        layout.addLayout(bottom)

        model.added.connect(self.add)
        model.item_changed.connect(self.change)
        model.cleared.connect(self.clear)
        model.busy_changed.connect(self.show_busy)
        model.providers.changed.connect(self.show_providers)
        self.show_providers()
        self.show_busy(model.busy())
        for index in range(len(model.items)):
            self.add(index)

    def show_providers(self) -> None:
        chosen = self.model.providers.chosen()
        self.providerBox.clear()
        for provider in self.model.providers.all():
            self.providerBox.addItem(f"{provider.name}", provider.name)
            self.providerBox.setItemData(
                self.providerBox.count() - 1,
                f"{provider.model} at {provider.url}",
                Qt.ToolTipRole,
            )
        if chosen is not None:
            self.providerBox.setCurrentIndex(self.providerBox.findData(chosen.name))
        else:
            self.providerBox.setPlaceholderText("no model server yet")

    def show_busy(self, busy: bool) -> None:
        self.sendButton.setIcon(theme.icon("stop" if busy else "send"))
        self.sendButton.setToolTip("Stop" if busy else "Send (Enter)")

    def send_or_stop(self) -> None:
        if self.model.busy():
            self.model.stop()
        else:
            self.send(self.input.toPlainText())

    def send(self, text: str) -> None:
        if self.model.busy() or not text.strip():
            return
        self.input.clear()
        self.model.send(text)

    def edit(self) -> None:
        ProvidersDialog(self.model.providers, self).exec()

    def add(self, index: int) -> None:
        item = self.model.items[index]
        widget = CallCard(item) if item.kind is Kind.CALL else Bubble(item)
        self.shown.append(widget)
        self.column.insertWidget(self.column.count() - 1, widget)

    def change(self, index: int) -> None:
        self.shown[index].show_item(self.model.items[index])

    def clear(self) -> None:
        for widget in self.shown:
            widget.deleteLater()
        self.shown.clear()

    def _grown(self, low: int, high: int) -> None:
        """New messages stay in sight while the person reads the newest."""
        if self._follow:
            self.scroll.verticalScrollBar().setValue(high)

    def _followed(self, value: int) -> None:
        self._follow = value >= self.scroll.verticalScrollBar().maximum() - 4
