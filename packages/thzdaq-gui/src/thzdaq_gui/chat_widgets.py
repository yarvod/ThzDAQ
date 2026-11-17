"""Widgets of a chat in a narrow dock, where nothing may widen it: text that
wraps anywhere and is as tall as it is (MessageView), a line cut to its width
(ElidedLabel), a card that folds to such a line (Fold), and what is attached
to a message (Chip).

A message the model writes grows piece by piece: MessageView adds what came
to what it shows rather than showing it all anew, so an answer costs the
window as much as its letters, not their square."""

import math
import re
from typing import Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QPainter,
    QPalette,
    QPixmap,
    QTextCursor,
    QTextFormat,
    QTextOption,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme

MIN_WIDTH = 60  # what a message asks of the dock's width at least
THUMB = 48  # the side of an image's thumbnail
FENCES = ("```", "~~~")
LIST_ITEM = re.compile(r"([-*+]|\d+[.)])\s")
LIST_START = "-*+0123456789"  # what a line still being written may make a list item
# Merges into the block before what is inserted, then goes: see _insert
PLACEHOLDER = "x"


def starts_block(line: str) -> bool:
    """Whether a line after a blank one starts a block of its own whatever
    comes after it: not indented (a list item's next paragraph, code) and not
    a list item (the list above going on), nor, while it is still being
    written, what may become one."""
    if not line or line[0].isspace():
        return False
    if line.endswith("\n"):
        return LIST_ITEM.match(line) is None
    return line[0] not in LIST_START


def settled(text: str, start: int) -> int:
    """Where the Markdown of text stays as it is whatever comes after it: the
    end of the last blank line after start outside a code fence, before a
    line that starts a block of its own; start when there is none. At start
    no fence is open: it is such an end, or 0."""
    found, at, fence = start, start, None
    lines = text[start:].splitlines(keepends=True)
    for index, line in enumerate(lines):
        at += len(line)
        stripped = line.strip()
        mark = next((m for m in FENCES if stripped.startswith(m)), None)
        if mark is not None:
            run = mark[0] * (len(stripped) - len(stripped.lstrip(mark[0])))
            if fence is None:
                fence = run
            elif run.startswith(fence) and stripped == run:
                fence = None
            continue
        if fence is not None or stripped or not line.endswith("\n"):
            continue
        if starts_block(lines[index + 1] if index + 1 < len(lines) else ""):
            found = at
    return found


class MessageView(QTextBrowser):
    """Text that wraps at the width it is given (a long word, a path or a
    line of code too) and is as tall as its text: it never widens the chat,
    and the chat scrolls, not the message. Markdown (the model's) shows its
    code in blocks of their own; plain text (the person's, a tool's answer)
    as it is.

    Text that goes on from what is shown is added: plain text by its new
    letters; Markdown by its blocks that will not change any more (settled),
    put in once, and the rest after them (the tail), put in anew each time.
    What was shown stays, a selection in it too."""

    def __init__(self, markdown: bool = True, mono: bool = False, parent=None):
        super().__init__(parent)
        self.markdown = markdown
        self._shown = ""  # the text shown
        self._settled = 0  # letters of it shown for good (Markdown)
        self._tail_at = 0  # where their blocks end in the document
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextBrowser.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        if mono:
            self.document().setDefaultFont(
                QFontDatabase.systemFont(QFontDatabase.FixedFont)
            )
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)

    def show_text(self, text: str) -> None:
        if text == self._shown:
            return
        goes_on = bool(self._shown) and text.startswith(self._shown)
        # A cursor follows the document's changes: its places, read now
        selected = self.textCursor().anchor(), self.textCursor().position()
        if not goes_on:
            stays = 0
            if self.markdown:
                self.document().clear()
                self._settled = self._tail_at = 0
                self._show_markdown(text)
            else:
                self.setPlainText(text)
        elif self.markdown:
            stays = self._tail_at
            self._show_markdown(text)
        else:
            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.End)
            stays = cursor.position()
            cursor.insertText(text[len(self._shown) :])
        self._keep(selected, stays)
        self._shown = text
        self._fit()

    def _keep(self, selected: Tuple[int, int], stays: int) -> None:
        """The person's selection (anchor, position) within what stayed (up to
        stays) as it was: Qt moves a cursor at the place text goes in along
        with the text."""
        anchor, position = selected
        now = self.textCursor()
        if max(anchor, position) > stays or (now.anchor(), now.position()) == (
            anchor,
            position,
        ):
            return
        kept = QTextCursor(self.document())
        kept.setPosition(anchor)
        kept.setPosition(position, QTextCursor.KeepAnchor)
        self.setTextCursor(kept)

    def text(self) -> str:
        return self.toPlainText()

    def set_color(self, color: str) -> None:
        palette = self.palette()
        palette.setColor(QPalette.Text, QColor(color))
        self.setPalette(palette)

    def _show_markdown(self, text: str) -> None:
        """text goes on from what is settled: the tail goes, what settled
        since comes after the settled blocks, then the new tail."""
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._tail_at)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        upto = settled(text, self._settled)
        if upto > self._settled:
            self._insert(cursor, text[self._settled : upto])
            self._settled, self._tail_at = upto, cursor.position()
        if text[self._settled :].strip():
            self._insert(cursor, text[self._settled :])

    def _insert(self, cursor: QTextCursor, markdown: str) -> None:
        """Markdown put in at the end, where cursor is; cursor ends after it.
        Qt merges the first block of what is inserted into the block at the
        cursor, which keeps its own format: a heading or a code block would
        lose its own. So a placeholder letter comes first, as a paragraph of
        its own: it merges into the last block shown, and then goes."""
        at = cursor.position()
        if at == 0:
            self.document().setMarkdown(markdown)
        else:
            cursor.insertMarkdown(f"{PLACEHOLDER}\n\n{markdown}")
            end = cursor.position()
            cursor.setPosition(at)
            cursor.deleteChar()
            cursor.setPosition(end - len(PLACEHOLDER))
        self._code_blocks(at)
        cursor.movePosition(QTextCursor.End)

    def _code_blocks(self, start: int) -> None:
        """Code wraps as the words do, on a darker ground, in the system's
        fixed font: Qt's Markdown keeps its lines whole, which would widen the
        chat, and takes a fixed font of its own. From the block at start on:
        those before it are done."""
        cursor = QTextCursor(self.document())
        family = QFontDatabase.systemFont(QFontDatabase.FixedFont).family()
        block = self.document().findBlock(start)
        while block.isValid():
            fragments = block.begin()
            while not fragments.atEnd():
                fragment = fragments.fragment()
                found = fragment.charFormat()
                if found.fontFixedPitch():
                    found.setFontFamilies([family])
                    cursor.setPosition(fragment.position())
                    cursor.setPosition(
                        fragment.position() + fragment.length(),
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    cursor.setCharFormat(found)
                fragments += 1
            found = block.blockFormat()
            if found.nonBreakableLines() or found.hasProperty(
                QTextFormat.BlockCodeFence
            ):
                found.setNonBreakableLines(False)
                found.setBackground(QColor(theme.BASE))
                found.setLeftMargin(4)
                found.setRightMargin(4)
                cursor.setPosition(block.position())
                cursor.setBlockFormat(found)
            block = block.next()

    def _fit(self, *_) -> None:
        height = math.ceil(self.document().size().height()) + 2 * self.frameWidth()
        if height != self.height():
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:
        """A new width lays the text out anew; a new height (_fit's, as the
        text grows) does not: QTextDocument.setTextWidth lays out the whole
        document even at the width it has."""
        super().resizeEvent(event)
        width = self.viewport().width()
        if width != self.document().textWidth():
            self.document().setTextWidth(width)
            self._fit()

    def sizeHint(self) -> QSize:
        return QSize(MIN_WIDTH, self.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(MIN_WIDTH, self.height())

    def wheelEvent(self, event) -> None:
        event.ignore()  # it has nothing to scroll: the chat scrolls


class ElidedLabel(QLabel):
    """A line cut with … to the width it is given; the whole of it in its
    tooltip."""

    def __init__(self, text: str = "", parent=None, mode=Qt.ElideRight):
        super().__init__(text, parent)
        self.mode = mode  # where the cut is: Qt.ElideMiddle keeps a path's end
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(text)
        self.setToolTip(text)

    def set_color(self, color: str) -> None:
        palette = self.palette()
        palette.setColor(QPalette.WindowText, QColor(color))
        self.setPalette(palette)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        shown = self.fontMetrics().elidedText(self.text(), self.mode, rect.width())
        self.style().drawItemText(
            painter, rect, int(self.alignment()), self.palette(), self.isEnabled(),
            shown, self.foregroundRole(),
        )  # fmt: skip


class Header(QWidget):
    """A card's line: a click on it folds or unfolds the card."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()


class Fold(QFrame):
    """A card that folds to its line: a chevron, an icon and a title cut to
    the width; unfolded, what it holds below. What it holds is made by build()
    when it is first unfolded: a folded card lays nothing out."""

    toggled = Signal(bool)

    def __init__(self, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.header = Header()
        self.header.setCursor(Qt.PointingHandCursor)
        line = QHBoxLayout(self.header)
        line.setContentsMargins(0, 2, 0, 2)
        line.setSpacing(4)
        self.chevron = QLabel()
        self.icon = QLabel()
        self.titleLabel = ElidedLabel()
        line.addWidget(self.chevron)
        line.addWidget(self.icon)
        line.addWidget(self.titleLabel, 1)
        self.body = QWidget()
        self.content_layout = QVBoxLayout(self.body)
        self.content_layout.setContentsMargins(18, 0, 0, 4)
        self.content_layout.setSpacing(4)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self.header.clicked.connect(lambda: self.set_expanded(not self.expanded()))
        self._built = False
        self._expanded = not expanded
        self.set_expanded(expanded)

    def build(self) -> None:
        """Fill the body (addWidget): called when the card is first unfolded."""

    def built(self) -> bool:
        return self._built

    def addWidget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def setTitle(self, title: str) -> None:
        self.titleLabel.setText(title)

    def title(self) -> str:
        return self.titleLabel.text()

    def set_icon(self, name: str, color: str) -> None:
        self.icon.setPixmap(theme.icon(name, color).pixmap(14, 14))

    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, on: bool) -> None:
        if on == self._expanded:
            return
        self._expanded = on
        if on and not self._built:
            self._built = True
            self.build()
        chevron = "chevron-down" if on else "chevron-right"
        self.chevron.setPixmap(theme.icon(chevron, theme.MUTED).pixmap(14, 14))
        self.body.setVisible(on)
        self.toggled.emit(on)


class Chip(QFrame):
    """What is attached: its thumbnail or icon and its name; × removes it
    when it can be removed."""

    removed = Signal()

    def __init__(
        self,
        name: str,
        image: Optional[bytes] = None,
        icon: str = "file-outline",
        removable: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("chip")
        self.setStyleSheet(
            f"#chip {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            " border-radius: 4px; }"
        )
        line = QHBoxLayout(self)
        line.setContentsMargins(4, 2, 2, 2)
        line.setSpacing(4)
        picture = QLabel()
        pixmap = QPixmap()
        if image is not None and pixmap.loadFromData(image):
            picture.setPixmap(
                pixmap.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            picture.setPixmap(theme.icon(icon).pixmap(16, 16))
        line.addWidget(picture)
        label = QLabel(name if len(name) <= 24 else name[:23] + "…")
        label.setToolTip(name)
        line.addWidget(label)
        if removable:
            remove = QToolButton()
            remove.setIcon(theme.icon("close"))
            remove.setAutoRaise(True)
            remove.setToolTip("Remove")
            remove.clicked.connect(self.removed)
            line.addWidget(remove)
