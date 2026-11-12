"""A highlight over a window: where an agent points the person (ui_highlight).

OverlayGuide draws a translucent accent frame around a widget (the anchor)
and a short text beside it, over the window the anchor is in: the main
window, a floating dock, the form dropped down under the run bar's settings
button. Clicks go through it to what is under it. It follows the anchor as
the anchor or a widget around it moves or resizes (a dock dragged, a section
unfolded, the form scrolled), and goes on a click anywhere, on Escape, as
the person types in the anchor, or when the anchor is hidden, moved to
another window or deleted.
"""

from typing import List

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from thzdaq_gui import theme

PAD = 4  # between the anchor and its frame
MARGIN = 8  # inside the bubble of the text
GAP = 6  # between the frame and the bubble
TEXT_WIDTH = 280  # the widest a line of the text gets
FILL_ALPHA = 48  # of the accent over the anchor
# Its place changes with these of the anchor or a widget around it
MOVES = (QEvent.Move, QEvent.Resize, QEvent.LayoutRequest)
# It goes with these of the anchor or a widget around it
ENDS = (QEvent.Hide, QEvent.ParentChange)


def around(anchor: QWidget) -> List[QWidget]:
    """The anchor and the widgets it is in, up to its window."""
    found = [anchor]
    while not found[-1].isWindow() and found[-1].parentWidget() is not None:
        found.append(found[-1].parentWidget())
    return found


class OverlayGuide(QWidget):
    gone = Signal()

    def __init__(self, anchor: QWidget, text: str):
        super().__init__(anchor.window())
        self.anchor = anchor
        self.text = text
        self.ended = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.watched = around(anchor)
        for widget in self.watched:
            widget.installEventFilter(self)
            if isinstance(widget, QScrollArea):
                widget.ensureWidgetVisible(anchor)
        # A click or a key anywhere in the program passes here first
        QApplication.instance().installEventFilter(self)
        anchor.destroyed.connect(self.dismiss)
        self.follow()
        self.show()

    def follow(self) -> None:
        """Over its whole window, on top, drawn where the anchor is now."""
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.update()

    def frame(self) -> QRect:
        """Around the anchor, in this widget's coordinates."""
        corner = self.anchor.mapTo(self.parentWidget(), QPoint(0, 0))
        return QRect(corner, self.anchor.size()).adjusted(-PAD, -PAD, PAD, PAD)

    def bubble(self, frame: QRect) -> QRect:
        """Where the text goes: under the frame, above it when there is no
        room below, inside the window."""
        flags = Qt.TextWordWrap
        size = self.fontMetrics().boundingRect(
            QRect(0, 0, TEXT_WIDTH, 0), flags, self.text
        )
        width, height = size.width() + 2 * MARGIN, size.height() + 2 * MARGIN
        area = self.rect()
        top = frame.bottom() + GAP
        if top + height > area.bottom():
            top = max(area.top(), frame.top() - GAP - height)
        left = min(max(frame.left(), area.left()), area.right() - width)
        return QRect(left, top, width, height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        accent = QColor(theme.ACCENT)
        fill = QColor(accent)
        fill.setAlpha(FILL_ALPHA)
        frame = self.frame()
        painter.setPen(QPen(accent, 2))
        painter.setBrush(fill)
        painter.drawRoundedRect(frame, 4, 4)
        if not self.text:
            return
        bubble = self.bubble(frame)
        painter.setPen(QPen(accent, 1))
        painter.setBrush(QColor(theme.PANEL))
        painter.drawRoundedRect(bubble, 4, 4)
        painter.setPen(QColor(theme.TEXT))
        inside = bubble.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        painter.drawText(inside, Qt.TextWordWrap, self.text)

    def eventFilter(self, watched, event) -> bool:
        if self.ended:
            return False
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            self.dismiss()
        elif kind == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape or self.typed_in(watched):
                self.dismiss()
        elif kind in ENDS:
            if watched in self.watched:
                self.dismiss()
        elif kind in MOVES:
            if watched in self.watched:
                self.follow()
        return False

    def typed_in(self, target) -> bool:
        """A key went to the anchor or a widget in it (a sweep's boxes)."""
        return isinstance(target, QWidget) and (
            target is self.anchor or self.anchor.isAncestorOf(target)
        )

    def dismiss(self) -> None:
        """Gone: hidden now, deleted later (with its event filters)."""
        if self.ended:
            return
        self.ended = True
        QApplication.instance().removeEventFilter(self)
        self.hide()
        self.gone.emit()
        self.deleteLater()
