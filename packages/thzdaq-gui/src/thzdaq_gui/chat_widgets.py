"""Widgets of a chat in a narrow dock, where nothing may widen it: text that
wraps anywhere and is as tall as it is (MessageView), a line cut to its width
(ElidedLabel), a card that folds to such a line (Fold), what is attached to a
message (Chip), how much of the model's context the chat fills (ContextRing);
buttons that flow into rows (Flow) and wrap their words (WrapButton), what
scrolls within past a height (Capped), and the chat's bar under the input:
what is chosen (PickerButton) and popups over it (Popup) with a list of
choices (Row) or a row of them (Segments).

A message the model writes grows piece by piece: MessageView adds what came
to what it shows rather than showing it all anew, so an answer costs the
window as much as its letters, not their square."""

import math
import re
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QTextCursor,
    QTextFormat,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QScrollArea,
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


def grouped(count: int) -> str:
    """46200 -> "46 200": a count of tokens, its thousands apart."""
    return f"{count:,}".replace(",", " ")


class ContextRing(QWidget):
    """How much of the model's context the conversation fills: a small ring
    that fills clockwise, grey, in the accent colour from WARN and red from
    FULL; its bare track while the model's limit is not known. Hovered it
    tells so (hovered: True as the pointer comes, False as it goes); clicked
    or pressed (Space, Enter), clicked."""

    hovered = Signal(bool)
    clicked = Signal()
    SIDE = 18
    LINE = 2.5
    WARN, FULL = 0.7, 0.9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._share: Optional[float] = None

    def show_share(self, share: Optional[float]) -> None:
        """0…1 of the context; None: the limit is not known."""
        if share != self._share:
            self._share = share
            self.update()

    def share(self) -> Optional[float]:
        return self._share

    def color(self) -> str:
        share = self._share or 0.0
        if share >= self.FULL:
            return theme.BAD
        return theme.ACCENT if share >= self.WARN else theme.MUTED

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        margin = self.LINE / 2 + 1
        rect = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        pen = QPen(QColor(theme.BORDER), self.LINE)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        if self._share:
            pen.setColor(QColor(self.color()))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, -round(self._share * 360 * 16))

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hovered.emit(False)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class Popup(QFrame):
    """A small window over the chat's bar, by its anchor (above it, else
    below): popped by a click it takes the clicks and closes on one
    elsewhere, as a menu does; shown while its anchor is hovered it never
    takes the focus, and goes as the pointer leaves the anchor (unhover)."""

    GAP = 4  # between the popup and its anchor

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("popup")
        self.setStyleSheet(
            f"#popup {{ background: {theme.WINDOW}; border: 1px solid {theme.BORDER}; }}"
        )
        self._hovering = False

    def pop(self, anchor: QWidget) -> None:
        self._show(anchor, Qt.Popup)

    def hover(self, anchor: QWidget) -> None:
        if not self.isVisible():
            self._show(anchor, Qt.ToolTip)

    def unhover(self) -> None:
        if self._hovering:
            self.hide()

    def hovering(self) -> bool:
        """Shown while its anchor is hovered (not popped)."""
        return self.isVisible() and self._hovering

    def _show(self, anchor: QWidget, kind: Qt.WindowType) -> None:
        self._hovering = kind == Qt.ToolTip
        self.setWindowFlags(kind | Qt.FramelessWindowHint)
        self.adjustSize()
        at = anchor.mapToGlobal(QPoint(0, 0))
        window = anchor.window().geometry()
        x = at.x()  # its left with the anchor's, else its right with the anchor's
        if x + self.width() > window.right():
            x = at.x() + anchor.width() - self.width()
        y = at.y() - self.height() - self.GAP
        if y < window.top():
            y = at.y() + anchor.height() + self.GAP
        self.move(max(x, window.left()), y)
        self.show()


class Choosable(Protocol):
    """A choice as a popup lists it (assistant.chat.Choice)."""

    id: str
    title: str
    tip: str


class Row(QAbstractButton):
    """A choice in a popup's list: a check before the one chosen, its name,
    and under it what it is in a line (cut; all of it in the tooltip)."""

    PAD, CHECK, MOST = 8, 14, 360

    def __init__(self, title: str, tip: str = "", parent=None):
        super().__init__(parent)
        self.setText(title)
        self.tip = tip
        self.setToolTip(tip)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def sizeHint(self) -> QSize:
        found = self.fontMetrics()
        wide = max(
            found.horizontalAdvance(self.text()), found.horizontalAdvance(self.tip)
        )
        lines = 2 if self.tip else 1
        return QSize(
            min(wide + 3 * self.PAD + self.CHECK, self.MOST),
            lines * found.lineSpacing() + self.PAD,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self.underMouse() or self.hasFocus():
            painter.fillRect(self.rect(), QColor(theme.PANEL))
        line = self.fontMetrics().lineSpacing()
        top = self.PAD // 2
        if self.isChecked():
            check = theme.icon("check", theme.ACCENT).pixmap(self.CHECK, self.CHECK)
            painter.drawPixmap(self.PAD, top + (line - self.CHECK) // 2, check)
        left = 2 * self.PAD + self.CHECK
        for at, (text, color) in enumerate(
            [(self.text(), theme.TEXT)]
            + ([(self.tip, theme.MUTED)] if self.tip else [])
        ):
            room = QRect(left, top + at * line, self.width() - left - self.PAD, line)
            cut = self.fontMetrics().elidedText(text, Qt.ElideRight, room.width())
            painter.setPen(QColor(color))
            painter.drawText(room, int(Qt.AlignLeft | Qt.AlignVCenter), cut)


class Segments(QFrame):
    """A choice of a few in one row, the one chosen lit (a model's reasoning
    effort); chosen tells the id the person picked."""

    chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segments")
        self.setStyleSheet(
            f"#segments {{ border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
            f"#segments QToolButton {{ border: none; padding: 2px 8px;"
            f" color: {theme.MUTED}; }}"
            f"#segments QToolButton:hover {{ color: {theme.TEXT}; }}"
            f"#segments QToolButton:checked {{ background: {theme.ACCENT};"
            f" color: {theme.BASE}; border-radius: 3px; }}"
        )
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(1, 1, 1, 1)
        self.row.setSpacing(0)
        self.buttons: Dict[str, QToolButton] = {}

    def show_choices(self, choices: Sequence[Choosable], chosen: Optional[str]) -> None:
        for button in self.buttons.values():
            button.deleteLater()
        self.buttons = {}
        for each in choices:
            button = QToolButton()
            button.setText(each.title)
            button.setToolTip(each.tip)
            button.setCheckable(True)
            button.setChecked(each.id == chosen)
            button.clicked.connect(lambda _=False, id=each.id: self.chosen.emit(id))
            self.buttons[each.id] = button
            self.row.addWidget(button)


class PickerButton(QToolButton):
    """What is chosen (a model, a mode), compact by the input: its name cut
    to the room it has and at most MOST wide, with an icon (after the name
    with after); a click opens what to choose from. Short of room, it keeps
    least pixels of its name (0: its icon alone)."""

    MOST = 170

    def __init__(self, icon: QIcon, after: bool = False, least: int = 0, parent=None):
        super().__init__(parent)
        self.least = least
        self.setAutoRaise(True)
        self.setIcon(icon)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        if after:
            self.setLayoutDirection(Qt.RightToLeft)  # a tool button's icon goes first
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._text = ""

    def show_text(self, text: str, tip: str = "") -> None:
        self._text = text
        self.setToolTip(tip or text)
        self.updateGeometry()
        self._cut()

    def whole(self) -> str:
        """Its name, uncut."""
        return self._text

    def _chrome(self) -> int:
        """What of its width is not its name (measured as QToolButton does)."""
        shown = self.fontMetrics().size(Qt.TextShowMnemonic, super().text()).width()
        return super().sizeHint().width() - shown

    def _name(self) -> int:
        """Its name's width, as eliding measures it (in fractions of a pixel)."""
        return math.ceil(QFontMetricsF(self.font()).horizontalAdvance(self._text))

    def sizeHint(self) -> QSize:
        wide = self._chrome() + self._name()
        return QSize(min(wide, self.MOST), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        name = min(self._name(), self.least)
        return QSize(self._chrome() + name, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._cut()

    def _cut(self) -> None:
        room = max(self.width() - self._chrome(), 0)
        cut = self.fontMetrics().elidedText(self._text, Qt.ElideRight, room)
        if cut != super().text():
            self.setText(cut)


class Flow(QLayout):
    """Items in rows, as many in a row as its width takes, the next ones
    below: buttons that never widen the chat. An item wider than the row is
    given the row's width (a WrapButton wraps its words then)."""

    def __init__(self, parent=None, spacing: int = 4):
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        found = QSize()
        for item in self._items:
            found = found.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return found + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _arrange(self, rect: QRect, place: bool) -> int:
        """The items laid out in rect's width (placed when place); the height
        they take."""
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), 0)
        gap = self.spacing()
        x, y, row = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            width = min(item.sizeHint().width(), area.width())
            height = (
                item.heightForWidth(width)
                if item.hasHeightForWidth()
                else item.sizeHint().height()
            )
            if x > area.x() and x + width > area.x() + area.width():
                x, y, row = area.x(), y + row + gap, 0
            if place:
                item.setGeometry(QRect(x, y, width, height))
            x += width + gap
            row = max(row, height)
        return y + row - rect.y() + margins.bottom()


def laid_out(text: str, font: QFont, width: float) -> QTextLayout:
    """Text in lines of width, cut between words, else anywhere (a path)."""
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    y = 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(width, 1.0))
        line.setPosition(QPointF(0, y))
        y += line.height()
    layout.endLayout()
    return layout


class WrapButton(QAbstractButton):
    """A button whose words wrap to the width it is given (a long answer an
    agent offers), an icon before them; as tall as its lines."""

    PAD, ICON, GAP = 6, 14, 6

    def __init__(self, icon: QIcon, text: str, parent=None):
        super().__init__(parent)
        self.setIcon(icon)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _room(self, width: int) -> int:
        """The width its words take within width."""
        return width - 2 * self.PAD - self.ICON - self.GAP

    def sizeHint(self) -> QSize:
        wide = self.fontMetrics().horizontalAdvance(self.text()) + 1
        width = wide + 2 * self.PAD + self.ICON + self.GAP
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return QSize(MIN_WIDTH, self.fontMetrics().lineSpacing() + 2 * self.PAD)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        lines = laid_out(self.text(), self.font(), self._room(width))
        return math.ceil(max(lines.boundingRect().height(), self.ICON)) + 2 * self.PAD

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        lit = self.underMouse() or self.hasFocus()
        painter.setPen(QPen(QColor(theme.ACCENT if lit else theme.BORDER), 1))
        painter.setBrush(QColor(theme.BORDER if self.isDown() else theme.PANEL))
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4
        )
        line = self.fontMetrics().lineSpacing()
        icon = self.icon().pixmap(self.ICON, self.ICON)
        painter.drawPixmap(self.PAD, self.PAD + (line - self.ICON) // 2, icon)
        painter.setPen(QColor(theme.TEXT))
        lines = laid_out(self.text(), self.font(), self._room(self.width()))
        lines.draw(painter, QPointF(self.PAD + self.ICON + self.GAP, self.PAD))


class Capped(QScrollArea):
    """What it holds, as tall as it is up to most pixels; taller, it scrolls
    within (never sideways, never wider than it is given)."""

    def __init__(self, widget: QWidget, most: int, parent=None):
        super().__init__(parent)
        self.most = most
        self.setWidget(widget)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.viewport().setAutoFillBackground(False)
        widget.setAutoFillBackground(False)
        widget.installEventFilter(self)  # its height follows what it holds

    def eventFilter(self, watched, event) -> bool:
        if watched is self.widget() and event.type() == QEvent.LayoutRequest:
            self.updateGeometry()
        return super().eventFilter(watched, event)

    def sizeHint(self) -> QSize:
        tall = min(self.widget().sizeHint().height(), self.most)
        return QSize(MIN_WIDTH, tall + 2 * self.frameWidth())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()
