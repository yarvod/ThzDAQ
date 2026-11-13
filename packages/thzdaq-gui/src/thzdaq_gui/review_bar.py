"""What the editor shows of a change looked at hunk by hunk (review.py): a
bar over the text (where the change comes from, how many hunks wait, ✓ and ✗
for all of them) and ✓ / ✗ beside each waiting hunk. Their words follow where
the change comes from: a change made outside is kept or undone, a proposal
accepted or rejected, the file compared with the text here taken or not."""

from typing import Callable, Dict, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from thzdaq_gui import theme
from thzdaq_gui.review import Review, Source

TAKE_ICON, LEAVE_ICON = "check", "close"
KEEP_MINE = "Keep mine"  # the text here, not the file's


class Words(NamedTuple):
    what: str  # where the change comes from
    take: str  # ✓
    leave: str  # ✗


WORDS: Dict[Source, Words] = {
    Source.OUTSIDE: Words("Changed outside", "Keep", "Undo"),
    Source.PROPOSED: Words("Proposed by the assistant", "Accept", "Reject"),
    Source.COMPARED: Words("The file on disk against your text", "Take the file's", KEEP_MINE),
}  # fmt: skip


def counted(review: Review) -> str:
    waiting = len(review.waiting())
    return f"{waiting} change" + ("" if waiting == 1 else "s")


def _button(icon: str, colour: str, style: Qt.ToolButtonStyle, slot) -> QToolButton:
    button = QToolButton()
    button.setIcon(theme.icon(icon, colour))
    button.setToolButtonStyle(style)
    button.setAutoRaise(True)
    button.clicked.connect(slot)
    return button


class ReviewBar(QFrame):
    """Over the text while a change is looked at."""

    def __init__(self, decide_all: Callable[[bool], None], parent: QWidget):
        """decide_all(take): every waiting hunk taken or left."""
        super().__init__(parent)
        self.setObjectName("review_bar")
        self.setStyleSheet(
            f"#review_bar {{ background: {theme.PANEL};"
            f" border-bottom: 1px solid {theme.ACCENT}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 1, 4, 1)
        self.label = QLabel()
        row.addWidget(self.label, 1)
        beside = Qt.ToolButtonTextBesideIcon
        self.takeAll = _button(TAKE_ICON, theme.GOOD, beside, lambda: decide_all(True))
        self.leaveAll = _button(
            LEAVE_ICON, theme.BAD, beside, lambda: decide_all(False)
        )
        row.addWidget(self.takeAll)
        row.addWidget(self.leaveAll)
        self.hide()

    def show_review(self, review: Review) -> None:
        words = WORDS[review.source]
        self.label.setText(f"{words.what} · {counted(review)}")
        self.takeAll.setText(f"{words.take} all")
        self.leaveAll.setText(f"{words.leave} all")
        self.show()


class HunkButtons(QFrame):
    """✓ and ✗ of one waiting hunk, beside its first line."""

    def __init__(
        self,
        review: Review,
        index: int,
        decide: Callable[[int, bool], None],
        parent: QWidget,
    ):
        """decide(index, take)."""
        super().__init__(parent)
        self.index = index
        self.setObjectName("hunk_buttons")
        self.setStyleSheet(
            f"#hunk_buttons {{ background: {theme.PANEL}; border-radius: 3px; }}"
        )
        words = WORDS[review.source]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        alone = Qt.ToolButtonIconOnly
        self.take = _button(TAKE_ICON, theme.GOOD, alone, lambda: decide(index, True))
        self.leave = _button(LEAVE_ICON, theme.BAD, alone, lambda: decide(index, False))
        self.take.setToolTip(words.take)
        self.leave.setToolTip(words.leave)
        row.addWidget(self.take)
        row.addWidget(self.leave)
