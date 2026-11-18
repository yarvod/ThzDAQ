"""What an agent asks before it acts, as a card of the chat (PermissionCard):
what it would do in a line; what it would act on (the command and its
folder, each file's changes folded to its path with the lines it adds and
removes, what else it is given, the files it touches), within a height and
scrolling past it; and a button per answer it offers, flowing into rows.
Nothing in it widens the chat: every text wraps, a long one scrolls within.
Once answered it tells the answer; once its turn ended first, that nobody
answered."""

from typing import Callable, Dict, Type

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from thzdaq_gui import theme
from thzdaq_gui.assistant.chat import Change, Files, Inputs, Note, Part, Run
from thzdaq_gui.chat_widgets import (
    Capped,
    ElidedLabel,
    Flow,
    Fold,
    MessageView,
    WrapButton,
)
from thzdaq_gui.models.assistant import Item, State

ANSWERED = "Answered: {option}"
UNANSWERED = "Not answered: the turn ended first"
DETAILS = 240  # pixels of what is asked shown at most; more scrolls within
DIFF_COLORS = {"+": theme.GOOD, "-": theme.BAD, "@": theme.MUTED}


def option_icon(allows: bool, always: bool) -> str:
    """An answer's icon: allow once, allow always, refuse."""
    return ("check-all" if always else "check") if allows else "close"


def command_view(command: Run) -> QWidget:
    """The command on a darker ground, as a terminal shows it; its folder
    under it."""
    holder = QFrame()
    holder.setObjectName("command")
    holder.setStyleSheet(
        f"#command {{ background: {theme.BASE}; border-radius: 4px; }}"
    )
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(6, 4, 6, 4)
    layout.setSpacing(2)
    line = MessageView(markdown=False, mono=True)
    line.show_text(command.line)
    layout.addWidget(line)
    if command.folder:
        folder = ElidedLabel(f"in {command.folder}", mode=Qt.ElideMiddle)
        folder.set_color(theme.MUTED)
        layout.addWidget(folder)
    return holder


def note_view(note: Note) -> QWidget:
    view = MessageView(markdown=False)
    view.show_text(note.text)
    return view


def inputs_view(inputs: Inputs) -> QWidget:
    view = MessageView(markdown=False, mono=True)
    view.show_text("\n".join(f"{name}: {value}" for name, value in inputs.values))
    view.set_color(theme.MUTED)
    return view


def files_view(files: Files) -> QWidget:
    view = MessageView(markdown=False, mono=True)
    view.show_text("\n".join(files.paths))
    return view


class ChangeCard(Fold):
    """A file an agent would change, folded to its path and the lines it
    adds and removes; unfolded, its diff, added lines green, removed red."""

    def __init__(self, change: Change, parent=None):
        super().__init__(expanded=False, parent=parent)
        self.change = change
        self.diff = None  # made when unfolded
        added, removed = change.counted()
        self.titleLabel.mode = Qt.ElideMiddle  # the file's name stays in sight
        self.setTitle(f"{change.path}  +{added} −{removed}")
        self.set_icon("file-document-edit-outline", theme.ACCENT)

    def build(self) -> None:
        self.diff = MessageView(markdown=False, mono=True)
        self.diff.show_text("\n".join(self.change.diff()))
        cursor = QTextCursor(self.diff.document())
        block = self.diff.document().begin()
        while block.isValid():
            color = DIFF_COLORS.get(block.text()[:1])
            if color is not None:
                cursor.setPosition(block.position())
                cursor.setPosition(
                    block.position() + block.length() - 1, QTextCursor.KeepAnchor
                )
                shown = QTextCharFormat()
                shown.setForeground(QColor(color))
                cursor.mergeCharFormat(shown)
            block = block.next()
        self.addWidget(self.diff)


# How each part of what is asked is shown
SHOWN: Dict[Type, Callable[..., QWidget]] = {
    Run: command_view,
    Change: ChangeCard,
    Note: note_view,
    Inputs: inputs_view,
    Files: files_view,
}


def part_widget(part: Part) -> QWidget:
    return SHOWN[type(part)](part)


class PermissionCard(QFrame):
    """What an agent asks before it acts (see the module)."""

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
        column = QWidget()
        parts = QVBoxLayout(column)
        parts.setContentsMargins(0, 0, 0, 0)
        parts.setSpacing(4)
        self.parts = [part_widget(part) for part in asked.parts]
        for widget in self.parts:
            parts.addWidget(widget)
        self.details = Capped(column, DETAILS)
        self.details.setVisible(bool(self.parts))
        self.buttons: Dict[str, WrapButton] = {}
        flow = Flow()
        for option in asked.options:
            button = WrapButton(
                theme.icon(option_icon(option.allows, option.always)), option.name
            )
            button.clicked.connect(lambda _=False, id=option.id: self.chosen.emit(id))
            self.buttons[option.id] = button
            flow.addWidget(button)
        self.choices = QWidget()
        self.choices.setLayout(flow)
        self.state = ElidedLabel()
        self.state.set_color(theme.MUTED)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        layout.addLayout(head)
        layout.addWidget(self.details)
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
