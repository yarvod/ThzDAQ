"""A panel that drops down under a button and shows one widget at a time
(the form of the measurement chosen in the run bar).

It has no title or buttons of a window: a click past it or on its button
again closes it, as Escape does. It is as wide and as tall as what it shows,
but no taller than the screen below its button: past that it scrolls. The
widgets it has shown stay in it, hidden, with what was typed into them.
"""

from typing import Optional

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme

MARGIN = 10


class DropDown(QFrame):
    visibility_changed = Signal(bool)

    def __init__(self, anchor: QAbstractButton):
        super().__init__(anchor, Qt.Popup)
        self.anchor = anchor
        self.setObjectName("dropDown")
        self.setStyleSheet(
            f"#dropDown {{ background: {theme.WINDOW}; "
            f"border: 1px solid {theme.ACCENT}; }}"
        )
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.column = QVBoxLayout(self.content)
        self.column.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.scroll.setWidget(self.content)
        # What it shows changed its size (a section folded): it follows
        self.content.installEventFilter(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(self.scroll)
        self.shown: Optional[QWidget] = None

    def show_widget(self, widget: QWidget) -> None:
        """Show this widget from now on; the one shown before stays, hidden."""
        if widget is self.shown:
            return
        if widget.parentWidget() is not self.content:
            self.column.addWidget(widget)
        if self.shown is not None:
            self.shown.hide()
        self.shown = widget
        widget.show()
        if self.isVisible():
            self.fit()

    def open(self) -> None:
        self.fit()
        self.show()

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.open()

    def fit(self) -> None:
        """As large as its content, under its button, within the screen."""
        below = self.anchor.mapToGlobal(QPoint(0, self.anchor.height()))
        screen = (self.anchor.screen() or self.screen()).availableGeometry()
        wanted = self.content.sizeHint()
        frame = 2 * self.layout().contentsMargins().top()
        # Wrapped text (a description) is as tall as the width it gets
        tall = wanted.height()
        if self.content.hasHeightForWidth():
            tall = max(tall, self.content.heightForWidth(wanted.width()))
        height = min(tall + frame, screen.bottom() + 1 - below.y())
        width = wanted.width() + frame
        scrolls = tall + frame > height
        if scrolls:  # room for the bar
            width += self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if scrolls else Qt.ScrollBarAlwaysOff
        )
        width = min(width, screen.width())
        x = min(max(below.x(), screen.left()), screen.right() - width + 1)
        self.setGeometry(x, below.y(), width, max(height, 0))

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.content
            and event.type() == QEvent.LayoutRequest
            and self.isVisible()
        ):
            self.fit()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        # Qt closes a popup on a press past it and then replays the press to
        # the widget under it: on its own button that would open it again.
        # A press there closes it without the replay, as QComboBox does.
        on_anchor = self.anchor.rect().contains(
            self.anchor.mapFromGlobal(event.globalPosition().toPoint())
        )
        self.setAttribute(Qt.WA_NoMouseReplay, on_anchor)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.visibility_changed.emit(False)
