"""Widgets of a chat in a narrow dock, where nothing may widen it: text that
wraps anywhere and is as tall as it is (MessageView), a line cut to its width
(ElidedLabel), a card that folds to such a line (Fold), and what is attached
to a message (Chip)."""

import math
from typing import Optional

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


class MessageView(QTextBrowser):
    """Text that wraps at the width it is given (a long word, a path or a
    line of code too) and is as tall as its text: it never widens the chat,
    and the chat scrolls, not the message. Markdown (the model's) shows its
    code in blocks of their own; plain text (the person's, a tool's answer)
    as it is."""

    def __init__(self, markdown: bool = True, mono: bool = False, parent=None):
        super().__init__(parent)
        self.markdown = markdown
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
        if self.markdown:
            self.setMarkdown(text)
            self._code_blocks()
        else:
            self.setPlainText(text)
        self._fit()

    def text(self) -> str:
        return self.toPlainText()

    def set_color(self, color: str) -> None:
        palette = self.palette()
        palette.setColor(QPalette.Text, QColor(color))
        self.setPalette(palette)

    def _code_blocks(self) -> None:
        """Code wraps as the words do, on a darker ground, in the system's
        fixed font: Qt's Markdown keeps its lines whole, which would widen the
        chat, and takes a fixed font of its own."""
        cursor = self.textCursor()
        family = QFontDatabase.systemFont(QFontDatabase.FixedFont).family()
        block = self.document().begin()
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
        super().resizeEvent(event)
        self.document().setTextWidth(self.viewport().width())
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
    the width; unfolded, what it holds below."""

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
        self._expanded = not expanded
        self.set_expanded(expanded)

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
