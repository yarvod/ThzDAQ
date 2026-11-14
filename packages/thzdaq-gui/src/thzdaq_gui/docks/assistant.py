"""The assistant's chat: the model server chosen, the messages (Markdown that
wraps to the dock's width; what the model thought and each tool call a card
folded to its line), what the turn does now and for how long, the tokens of
the chat and how much of the model's context it fills, the input with what
is attached (files, images; Ctrl+V and dropping too), Send and Stop. While
the assistant works, what is sent joins at its next step. A view of
AssistantModel."""

import json
from typing import Any, Dict, List

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.attachments import Attachment, AttachmentError, Kind as Given
from thzdaq_gui.chat_widgets import Chip, ElidedLabel, Fold, MessageView
from thzdaq_gui.docks.providers import ProvidersDialog
from thzdaq_gui.folders import ATTACHMENTS
from thzdaq_gui.models.assistant import (
    AssistantModel,
    Item,
    Kind,
    State,
    tokens,
)

PLACEHOLDER = "Ask the assistant (Enter sends, Shift+Enter: a new line)"
BUSY_PLACEHOLDER = "Write more: it joins at the assistant's next step (Enter)"
QUEUED = "queued: goes in at the next step"
UNSENT = "not sent: the turn was stopped"
INPUT_LINES = (3, 10)  # the input's height in lines, least and most
STATE_ICONS = {  # of a call: its icon and colour
    State.RUNNING: ("progress-clock", theme.ACCENT),
    State.DONE: ("check", theme.GOOD),
    State.REFUSED: ("close-circle-outline", theme.BAD),
    State.STOPPED: ("stop-circle-outline", theme.MUTED),
}
STATE_COLORS = {  # of what a call answered
    State.RUNNING: theme.TEXT,
    State.DONE: theme.TEXT,
    State.REFUSED: theme.BAD,
    State.STOPPED: theme.MUTED,
}


class MessageInput(QPlainTextEdit):
    """Enter sends what is typed; Shift+Enter starts a new line. An image
    pasted or dropped, and files, are attached rather than typed. It grows
    with its text, up to a few lines."""

    submitted = Signal(str)
    image_given = Signal(QImage)
    files_given = Signal(list)  # paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)
        self._fit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if enter and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit(self.toPlainText())
            return
        super().keyPressEvent(event)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return (
            source.hasImage()
            or source.hasUrls()
            or super().canInsertFromMimeData(source)
        )

    def insertFromMimeData(self, source: QMimeData) -> None:
        files = [url.toLocalFile() for url in source.urls() if url.isLocalFile()]
        if files:
            self.files_given.emit(files)
        elif source.hasImage():
            self.image_given.emit(QImage(source.imageData()))
        else:
            super().insertFromMimeData(source)

    def _fit(self, *_) -> None:
        line = self.fontMetrics().lineSpacing()
        least, most = INPUT_LINES
        lines = min(max(self.document().size().height(), least), most)
        self.setFixedHeight(int(lines * line) + 12)


def png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def fenced(text: str) -> str:
    """Text as a Markdown code block, whatever backticks it holds."""
    fence = "`" * max(3, longest_run(text, "`") + 1)
    return f"{fence}\n{text}\n{fence}"


def longest_run(text: str, letter: str) -> int:
    longest = current = 0
    for found in text:
        current = current + 1 if found == letter else 0
        longest = max(longest, current)
    return longest


def arguments_text(arguments: Dict[str, Any]) -> str:
    """A call's arguments as Markdown: a long or many-lined one (a script)
    as code."""
    lines: List[str] = []
    for key, value in arguments.items():
        shown = (
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        )
        if "\n" in shown or len(shown) > 80:
            lines.append(f"**{key}**\n\n{fenced(shown)}")
        else:
            lines.append(f"**{key}**: `{shown}`" if shown else f"**{key}**: ―")
    return "\n\n".join(lines) or "*no arguments*"


class CallCard(Fold):
    """A tool call, folded to its line; unfolded: its arguments and answer."""

    def __init__(self, item: Item, parent=None):
        super().__init__(expanded=False, parent=parent)
        self.arguments = MessageView(markdown=True)
        self.answer = MessageView(markdown=False, mono=True)
        self.addWidget(self.arguments)
        self.addWidget(self.answer)
        self._shown: Dict[str, Any] = {}
        self.show_item(item)

    def show_item(self, item: Item) -> None:
        self.setTitle(item.summary())
        self.set_icon(*STATE_ICONS[item.state])
        if item.arguments != self._shown:
            self._shown = dict(item.arguments)
            self.arguments.show_text(arguments_text(item.arguments))
        self.answer.show_text(item.text)
        self.answer.setVisible(bool(item.text))
        self.answer.set_color(STATE_COLORS[item.state])


class ThoughtCard(Fold):
    """What the model thought before it answered, folded to how long."""

    def __init__(self, item: Item, parent=None):
        super().__init__(expanded=False, parent=parent)
        self.thought = MessageView(markdown=False)
        self.thought.set_color(theme.MUTED)
        self.addWidget(self.thought)
        self.titleLabel.set_color(theme.MUTED)
        self.show_item(item)

    def show_item(self, item: Item) -> None:
        self.setTitle(item.thought_title())
        running = item.state is State.RUNNING
        self.set_icon(
            "head-lightbulb-outline", theme.ACCENT if running else theme.MUTED
        )
        self.thought.show_text(item.text)


class Bubble(QFrame):
    """What the person wrote, with what is attached and whether it waits; or
    what the model answered, or a note."""

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
        layout.setSpacing(4)
        self.label = MessageView(markdown=item.kind is Kind.ANSWER)
        if item.kind is Kind.NOTE:
            self.label.set_color(theme.MUTED)
        layout.addWidget(self.label)
        if item.attachments:
            row = QHBoxLayout()
            row.setSpacing(4)
            for given in item.attachments:
                row.addWidget(chip(given, removable=False))
            row.addStretch()
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(scrolled(holder))
        self.state = ElidedLabel()
        self.state.set_color(theme.MUTED)
        layout.addWidget(self.state)
        self.show_item(item)

    def show_item(self, item: Item) -> None:
        self.label.show_text(item.text)
        self.label.setVisible(bool(item.text))
        told = QUEUED if item.queued else UNSENT if item.unsent else ""
        self.state.setText(told)
        self.state.setVisible(bool(told))


class Stats(ElidedLabel):
    """How long a turn took and its tokens, small, on the right."""

    def __init__(self, item: Item, parent=None):
        super().__init__(item.text, parent)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.set_color(theme.MUTED)
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * 0.85)
        self.setFont(font)

    def show_item(self, item: Item) -> None:
        self.setText(item.text)


def chip(given: Attachment, removable: bool = True) -> Chip:
    image = given.data if given.kind is Given.IMAGE else None
    icon = "file-document-outline" if given.kind is Given.TEXT else "file-outline"
    return Chip(given.name, image, icon, removable)


def scrolled(widget: QWidget) -> QScrollArea:
    """A row that scrolls sideways rather than widen the chat."""
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    area.setFixedHeight(widget.sizeHint().height() + 14)
    return area


def item_widget(item: Item) -> QWidget:
    if item.kind is Kind.CALL:
        return CallCard(item)
    if item.kind is Kind.THOUGHT:
        return ThoughtCard(item)
    if item.kind is Kind.STATS:
        return Stats(item)
    return Bubble(item)


class AssistantWidget(QWidget):
    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.shown: List[QWidget] = []  # a widget per item of the model
        self.attached: List[Attachment] = []  # for the next message

        self.providerBox = QComboBox()
        self.providerBox.setToolTip("The model's server")
        self.providerBox.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.providerBox.setMinimumContentsLength(6)
        self.providerBox.activated.connect(
            lambda index: model.providers.choose(self.providerBox.itemText(index))
        )
        settings = self._button("cog-outline", "Model servers…", self.edit)
        new = self._button("chat-plus-outline", "New chat", model.new_chat)
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
        messages.setMinimumWidth(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(messages)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumWidth(0)
        bar = self.scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._grown)
        bar.valueChanged.connect(self._followed)
        self._follow = True  # at the bottom: new messages stay in sight

        # What the turn does now, and the tokens
        self.spinner = QToolButton()
        self.spinner.setAutoRaise(True)
        self.spinner.setEnabled(True)
        self.spinner.setFocusPolicy(Qt.NoFocus)
        self._spin = theme.Spinner(self.spinner)
        self.spinner.setIcon(self._spin.icon)
        self.phaseLabel = ElidedLabel()
        self.phaseLabel.set_color(theme.ACCENT)
        self.usageLabel = ElidedLabel()
        self.usageLabel.set_color(theme.MUTED)
        self.usageLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.contextBar = QProgressBar()
        self.contextBar.setFixedSize(48, 6)
        self.contextBar.setTextVisible(False)
        self.contextBar.setRange(0, 1000)
        status = QHBoxLayout()
        status.setSpacing(4)
        status.addWidget(self.spinner)
        status.addWidget(self.phaseLabel, 1)
        status.addWidget(self.usageLabel, 1)
        status.addWidget(self.contextBar, 0, Qt.AlignVCenter)
        self.ticker = QTimer(self)  # the seconds of the turn, while it runs
        self.ticker.setInterval(1000)
        self.ticker.timeout.connect(self.tick)

        # What goes with the next message
        self.chips = QHBoxLayout()
        self.chips.setContentsMargins(0, 0, 0, 0)
        self.chips.setSpacing(4)
        self.chips.addStretch()
        holder = QWidget()
        holder.setLayout(self.chips)
        self.attachments = scrolled(holder)
        self.attachments.setFixedHeight(68)
        self.attachments.hide()

        self.input = MessageInput()
        self.input.setPlaceholderText(PLACEHOLDER)
        self.input.submitted.connect(self.send)
        self.input.image_given.connect(self.attach_image)
        self.input.files_given.connect(self.attach_files)
        self.attachButton = self._button(
            "paperclip", "Attach files or images (or paste, or drop them)", self.pick
        )
        self.sendButton = self._button("send", "Send (Enter)", self.send_typed)
        self.stopButton = self._button("stop", "Stop the assistant", model.stop)
        buttons = QVBoxLayout()
        buttons.setSpacing(2)
        buttons.addStretch()
        for button in (self.attachButton, self.stopButton, self.sendButton):
            buttons.addWidget(button)
        bottom = QHBoxLayout()
        bottom.addWidget(self.input, 1)
        bottom.addLayout(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.scroll, 1)
        layout.addLayout(status)
        layout.addWidget(self.attachments)
        layout.addLayout(bottom)

        model.added.connect(self.add)
        model.item_changed.connect(self.change)
        model.cleared.connect(self.clear)
        model.busy_changed.connect(self.show_busy)
        model.phase_changed.connect(lambda phase: self.tick())
        model.usage_changed.connect(self.show_usage)
        model.providers.changed.connect(self.show_providers)
        self.show_providers()
        self.show_busy(model.busy())
        self.show_usage()
        for index in range(len(model.items)):
            self.add(index)

    @staticmethod
    def _button(icon: str, tip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setIcon(theme.icon(icon))
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

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
        self.stopButton.setVisible(busy)
        self._spin.run(busy)
        self.spinner.setVisible(busy)
        self.input.setPlaceholderText(BUSY_PLACEHOLDER if busy else PLACEHOLDER)
        if busy:
            self.ticker.start()
        else:
            self.ticker.stop()
        self.tick()

    def tick(self) -> None:
        """What the turn does and for how long; a thought's seconds."""
        model = self.model
        phase = model.phase
        self.phaseLabel.setText(f"{phase}… {model.elapsed():.0f} s" if phase else "")
        self.phaseLabel.setVisible(bool(phase))
        for index, item in enumerate(model.items):
            if item.kind is Kind.THOUGHT and item.state is State.RUNNING:
                self.shown[index].show_item(item)

    def show_usage(self) -> None:
        used = self.model.usage
        limit = self.model.context_limit()
        context = ""
        if used.context:
            context = f"context {tokens(used.context)}"
            if limit:
                context += f" / {tokens(limit)} ({100 * used.context / limit:.0f}%)"
        told = " · ".join(filter(None, (context, used.told())))
        self.usageLabel.setText(told)
        self.usageLabel.setToolTip(
            f"The conversation fills {used.context} tokens of the model's context"
            + (f" of {limit}" if limit else " (its size: the model server's Test)")
            + f".\nThis chat: {used.read} tokens read, {used.written} written"
            + (f" ({used.reasoning} thinking)" if used.reasoning else "")
            + f", in {used.steps or 0} steps."
        )
        self.contextBar.setVisible(bool(limit and used.context))
        if limit:
            self.contextBar.setValue(min(1000, int(1000 * used.context / limit)))

    # What goes with the next message
    def pick(self) -> None:
        paths = self.model.session.folders.open_paths(
            self, ATTACHMENTS, "Attach to the message", "Any file (*)"
        )
        self.attach_files([str(path) for path in paths])

    def attach_files(self, paths: List[str]) -> None:
        refused = []
        for path in paths:
            try:
                self._attach(Attachment.of_file(path))
            except AttachmentError as e:
                refused.append(str(e))
        if refused:
            QMessageBox.warning(self, "Attach", "\n".join(refused))

    def attach_image(self, image: QImage) -> None:
        if not image.isNull():
            self._attach(Attachment.image(png(image)))

    def _attach(self, given: Attachment) -> None:
        self.attached.append(given)
        shown = chip(given)
        shown.removed.connect(lambda: self._detach(given, shown))
        self.chips.insertWidget(self.chips.count() - 1, shown)
        self.attachments.show()

    def _detach(self, given: Attachment, shown: QWidget) -> None:
        self.attached.remove(given)
        shown.deleteLater()
        self.attachments.setVisible(bool(self.attached))

    def _clear_attached(self) -> None:
        self.attached.clear()
        while self.chips.count() > 1:
            self.chips.takeAt(0).widget().deleteLater()
        self.attachments.hide()

    # Sending
    def send_typed(self) -> None:
        self.send(self.input.toPlainText())

    def send(self, text: str) -> None:
        if not text.strip() and not self.attached:
            return
        self.input.clear()
        attached, self.attached = list(self.attached), []
        self._clear_attached()
        self._follow = True
        self.model.send(text, attached)

    def edit(self) -> None:
        ProvidersDialog(self.model.providers, self).exec()

    def add(self, index: int) -> None:
        widget = item_widget(self.model.items[index])
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
