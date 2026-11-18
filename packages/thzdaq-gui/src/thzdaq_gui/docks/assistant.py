"""The assistant's chat: its modes as tabs on top (the built-in assistant,
Codex; each a chat of its own) with History (a page of the dock: the chats kept in
the workspace, chat_history.py), New chat and the settings; the messages
(Markdown that wraps to the dock's width; what the model thought and each
tool call a card folded to its line; what an agent asks before it acts, a
card with a button per answer it offers); what the turn does now and for how
long, beside a thin bar of how much of the model's context the chat fills
and the tokens in a popup; the input with what is attached (files, images;
Ctrl+V and dropping too), and under it the mode's model, Send and Stop.
While the assistant works, what is sent joins at its next step. A view of
AssistantModel, of the mode it shows."""

import json
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.attachments import Attachment, AttachmentError, Kind as Given
from thzdaq_gui.chat_widgets import (
    Chip,
    ContextBar,
    ElidedLabel,
    Fold,
    MessageView,
    grouped,
)
from thzdaq_gui.docks.assistant_settings import TITLE as SETTINGS, AssistantSettings
from thzdaq_gui.docks.chat_history import HistoryPage
from thzdaq_gui.folders import ATTACHMENTS
from thzdaq_gui.models.assistant import (
    AssistantModel,
    Item,
    Kind,
    State,
    Tokens,
)

PLACEHOLDER = "Ask the assistant (Enter sends, Shift+Enter: a new line)"
BUSY_PLACEHOLDER = "Write more: it joins at the assistant's next step (Enter)"
QUEUED = "queued: goes in at the next step"
UNSENT = "not sent: the turn was stopped"
NO_MODEL = "no model yet"
USAGE_TIP = "Tokens of the last answer and of this chat"
HISTORY_TIP = "History: the chats of this workspace"
UNKNOWN = "—"  # tokens the model's server did not tell
UNANSWERED = "Not answered: the turn ended first"
ANSWERED = "Answered: {option}"
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
        self.arguments: Optional[MessageView] = None  # made when unfolded
        self.answer: Optional[MessageView] = None
        self._shown: Dict[str, Any] = {}
        self.item = item
        self.show_item(item)

    def build(self) -> None:
        self.arguments = MessageView(markdown=True)
        self.answer = MessageView(markdown=False, mono=True)
        self.addWidget(self.arguments)
        self.addWidget(self.answer)
        self.show_item(self.item)

    def show_item(self, item: Item) -> None:
        self.item = item
        self.setTitle(item.summary())
        self.set_icon(*STATE_ICONS[item.state])
        if not self.built():
            return
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
        self.thought: Optional[MessageView] = None  # made when unfolded
        self.titleLabel.set_color(theme.MUTED)
        self.item = item
        self.show_item(item)

    def build(self) -> None:
        self.thought = MessageView(markdown=False)
        self.thought.set_color(theme.MUTED)
        self.addWidget(self.thought)
        self.show_item(self.item)

    def show_item(self, item: Item) -> None:
        self.item = item
        self.setTitle(item.thought_title())
        running = item.state is State.RUNNING
        self.set_icon(
            "head-lightbulb-outline", theme.ACCENT if running else theme.MUTED
        )
        if self.built():
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


class PermissionCard(QFrame):
    """What an agent asks before it acts: what it would do, more of it (the
    command, the file), and a button per answer it offers; once answered,
    the answer; once its turn ended first, that nobody answered."""

    chosen = Signal(str)  # the id of the option the person picked

    def __init__(self, item: Item, parent=None):
        super().__init__(parent)
        self.setObjectName("asked")
        self.setStyleSheet(
            f"#asked {{ border: 1px solid {theme.ACCENT}; border-radius: 6px; }}"
        )
        asked = item.asked
        icon = QLabel()
        icon.setPixmap(theme.icon("shield-alert-outline", theme.ACCENT).pixmap(16, 16))
        self.titleLabel = MessageView(markdown=False)
        self.titleLabel.show_text(asked.title)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(icon, 0, Qt.AlignTop)
        head.addWidget(self.titleLabel, 1)
        self.detail = MessageView(markdown=False, mono=True)
        self.detail.show_text(asked.detail)
        self.detail.setVisible(bool(asked.detail))
        self.buttons: Dict[str, QPushButton] = {}
        row = QHBoxLayout()
        row.setSpacing(4)
        for option in asked.options:
            button = QPushButton(
                theme.icon("check" if option.allows else "close"), option.name
            )
            button.clicked.connect(lambda _=False, id=option.id: self.chosen.emit(id))
            self.buttons[option.id] = button
            row.addWidget(button)
        row.addStretch()
        self.choices = QWidget()
        self.choices.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self.state = ElidedLabel()
        self.state.set_color(theme.MUTED)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(self.detail)
        layout.addWidget(self.choices)
        layout.addWidget(self.state)
        self.show_item(item)

    def show_item(self, item: Item) -> None:
        waiting = item.state is State.RUNNING
        self.choices.setVisible(waiting)
        names = {option.id: option.name for option in item.asked.options}
        told = (
            ""
            if waiting
            else ANSWERED.format(option=names[item.chosen])
            if item.chosen is not None
            else UNANSWERED
        )
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


def item_widget(item: Item, answer: Callable[[str], None]) -> QWidget:
    """The widget of an item; answer: what a question's card tells once the
    person picked an option."""
    if item.kind is Kind.PERMISSION:
        card = PermissionCard(item)
        card.chosen.connect(answer)
        return card
    if item.kind is Kind.CALL:
        return CallCard(item)
    if item.kind is Kind.THOUGHT:
        return ThoughtCard(item)
    if item.kind is Kind.STATS:
        return Stats(item)
    return Bubble(item)


class UsageView(QWidget):
    """The tokens in and out of the last answer and of the chat, as the
    model's server told them (— where it told none); out with what of it
    the model thought."""

    ROWS = ("Last answer", "This chat")
    COLUMNS = ("In", "Out")

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(14)
        for column, title in enumerate(self.COLUMNS, 1):
            grid.addWidget(self._label(title, theme.MUTED), 0, column, Qt.AlignRight)
        self.cells: Dict[tuple, QLabel] = {}
        for row, title in enumerate(self.ROWS, 1):
            grid.addWidget(self._label(title, theme.MUTED), row, 0)
            for column in range(1, len(self.COLUMNS) + 1):
                self.cells[row, column] = self._label("", theme.TEXT)
                grid.addWidget(self.cells[row, column], row, column, Qt.AlignRight)

    @staticmethod
    def _label(text: str, color: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color: {color};")
        return label

    def show_usage(self, last: Tokens, chat: Tokens) -> None:
        for row, used in enumerate((last, chat), 1):
            written = grouped(used.written)
            if used.reasoning:
                written += f" ({grouped(used.reasoning)} thinking)"
            told = (grouped(used.read), written) if used.known() else (UNKNOWN,) * 2
            for column, text in enumerate(told, 1):
                self.cells[row, column].setText(text)

    def told(self) -> List[List[str]]:
        """The rows as shown: in and out of the last answer, of the chat."""
        return [
            [self.cells[row, column].text() for column in range(1, 3)]
            for row in range(1, 3)
        ]


class AssistantWidget(QWidget):
    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.shown: List[QWidget] = []  # a widget per item of the mode shown
        self.attached: List[Attachment] = []  # for the next message

        # On top: the modes on the left, the chat's actions on the right
        self.modeTabs = QTabBar()
        self.modeTabs.setObjectName("modes")
        self.modeTabs.setDrawBase(False)
        self.modeTabs.setExpanding(False)
        self.modeTabs.setStyleSheet(
            "#modes::tab { background: transparent; border: none;"
            f" padding: 3px 10px; color: {theme.MUTED}; }}"
            f"#modes::tab:selected {{ color: {theme.TEXT};"
            f" border-bottom: 2px solid {theme.ACCENT}; }}"
            f"#modes::tab:hover {{ color: {theme.TEXT}; }}"
        )
        for mode in model.modes:
            self.modeTabs.addTab(mode.title)
        self.modeTabs.currentChanged.connect(model.show_mode)
        self.historyButton = QToolButton()  # down: the chats kept in the chat's place
        self.historyButton.setIcon(theme.icon("history"))
        self.historyButton.setToolTip(HISTORY_TIP)
        self.historyButton.setCheckable(True)
        self.historyButton.toggled.connect(self.show_history)
        self.newButton = self._button("chat-plus-outline", "New chat", self.new_chat)
        self.settingsButton = self._button("cog-outline", f"{SETTINGS}…", self.edit)
        top = QHBoxLayout()
        top.setSpacing(2)
        top.addWidget(self.modeTabs)
        top.addStretch()
        for button in (self.historyButton, self.newButton, self.settingsButton):
            top.addWidget(button)

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

        # What the turn does now; the context the chat fills and its tokens
        self.spinner = QToolButton()
        self.spinner.setAutoRaise(True)
        self.spinner.setEnabled(True)
        self.spinner.setFocusPolicy(Qt.NoFocus)
        self._spin = theme.Spinner(self.spinner)
        self.spinner.setIcon(self._spin.icon)
        self.phaseLabel = ElidedLabel()
        self.phaseLabel.set_color(theme.ACCENT)
        self.contextBar = ContextBar()
        self.contextBar.setFixedWidth(72)
        self.usageView = UsageView()
        usage = QMenu(self)
        shown = QWidgetAction(usage)
        shown.setDefaultWidget(self.usageView)
        usage.addAction(shown)
        usage.aboutToShow.connect(self.show_tokens)
        self.usageButton = QToolButton()
        self.usageButton.setAutoRaise(True)
        self.usageButton.setIcon(theme.icon("counter", theme.MUTED))
        self.usageButton.setToolTip(USAGE_TIP)
        self.usageButton.setPopupMode(QToolButton.InstantPopup)
        self.usageButton.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        self.usageButton.setMenu(usage)
        status = QHBoxLayout()
        status.setSpacing(4)
        status.addWidget(self.spinner)
        status.addWidget(self.phaseLabel, 1)
        status.addStretch()  # takes the room while the phase is hidden
        status.addWidget(self.contextBar, 0, Qt.AlignVCenter)
        status.addWidget(self.usageButton)
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

        # Under the input: the model that answers, what to attach, Stop, Send
        self.modelBox = QComboBox()
        self.modelBox.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.modelBox.setMinimumContentsLength(6)
        self.modelBox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.modelBox.setMaximumWidth(220)
        self.modelBox.activated.connect(
            lambda index: model.choose_model(self.modelBox.itemData(index))
        )
        self.attachButton = self._button(
            "paperclip", "Attach files or images (or paste, or drop them)", self.pick
        )
        self.sendButton = self._button("send", "Send (Enter)", self.send_typed)
        self.stopButton = self._button("stop", "Stop the assistant", model.stop)
        bottom = QHBoxLayout()
        bottom.setSpacing(2)
        bottom.addWidget(self.modelBox, 1)
        bottom.addWidget(self.attachButton)
        bottom.addStretch()
        bottom.addWidget(self.stopButton)
        bottom.addWidget(self.sendButton)

        # The chat, and the chats kept in its place while History is down:
        # the chat's widgets stay as they are meanwhile
        self.chatPage = QWidget()
        page = QVBoxLayout(self.chatPage)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(4)
        page.addWidget(self.scroll, 1)
        page.addLayout(status)
        page.addWidget(self.attachments)
        page.addWidget(self.input)
        page.addLayout(bottom)
        self.historyPage = HistoryPage(model)
        self.historyPage.chosen.connect(self.open_chat)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.chatPage)
        self.pages.addWidget(self.historyPage)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self.pages, 1)

        model.added.connect(self.add)
        model.item_changed.connect(self.change)
        model.cleared.connect(self.clear)
        model.busy_changed.connect(self.show_busy)
        model.phase_changed.connect(lambda phase: self.tick())
        model.usage_changed.connect(self.show_usage)
        model.models_changed.connect(self.show_models)
        model.mode_changed.connect(self.show_mode)
        self.show_mode()

    @staticmethod
    def _button(icon: str, tip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setIcon(theme.icon(icon))
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def show_mode(self) -> None:
        """The mode shown, all of it anew: its messages (a widget each), its
        turn, its tokens and its models; its chats kept, while History is
        down."""
        self.modeTabs.setCurrentIndex(self.model.modes.index(self.model.mode))
        if self.historyButton.isChecked():
            self.model.find_chats()
        self.clear()
        self._follow = True
        for index in range(len(self.model.items)):
            self.add(index)
        self.show_busy(self.model.busy())
        self.show_usage()
        self.show_models()

    def show_models(self) -> None:
        box = self.modelBox
        box.clear()
        for choice in self.model.models():
            box.addItem(choice.title, choice.id)
            box.setItemData(box.count() - 1, choice.tip, Qt.ToolTipRole)
        chosen = self.model.chosen_model()
        box.setCurrentIndex(box.findData(chosen) if chosen is not None else -1)
        box.setPlaceholderText(NO_MODEL)
        box.setToolTip(box.currentData(Qt.ToolTipRole) or "")

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
        """What the turn does and for how long; the seconds of the thought
        the model thinks now."""
        model = self.model
        phase = model.phase
        self.phaseLabel.setText(f"{phase}… {model.elapsed():.0f} s" if phase else "")
        self.phaseLabel.setVisible(bool(phase))
        thinking = model.thinking()
        if thinking is not None:
            self.shown[thinking].show_item(model.items[thinking])

    def show_usage(self) -> None:
        self.contextBar.show_context(
            self.model.usage.context, self.model.context_limit()
        )
        if self.usageView.isVisible():
            self.show_tokens()

    def show_tokens(self) -> None:
        self.usageView.show_usage(self.model.last_usage, self.model.usage)

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
        model = self.model
        AssistantSettings(model.providers, model.instructions, model.codex, self).exec()

    # The chats kept
    def show_history(self, shown: bool) -> None:
        """The chats of the workspace in place of the chat (listed anew), or
        the chat again."""
        if shown:
            self.model.find_chats()
            self.historyPage.show_chats()
            self.pages.setCurrentWidget(self.historyPage)
            self.historyPage.search.setFocus()
        else:
            self.pages.setCurrentWidget(self.chatPage)

    def open_chat(self, id: str) -> None:
        self.historyButton.setChecked(False)
        self._follow = True
        self.model.open_chat(id)

    def new_chat(self) -> None:
        self.historyButton.setChecked(False)
        self.model.new_chat()

    def add(self, index: int) -> None:
        widget = item_widget(
            self.model.items[index], lambda option: self.model.answer(index, option)
        )
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
