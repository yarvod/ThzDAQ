"""The box of the assistant's code in an editor, under the line of the
cursor (over it when there is no room below). Ctrl+I opens it for the
person to say in words what code to write there: Enter asks. A Fix opens it
too, with what it mends in place of the words. Esc or ✕ closes it and drops
a question on its way.

While the assistant writes, the box follows its question (models/hints.py,
Request): a turning icon, what it does and for how long (Thinking… 4 s) and
its model, the server in their tooltip; what the model thinks, folded (a
click opens it); the code as it comes, a preview that grows up to
PREVIEW_LINES and then follows its end. Each take of pieces is added at the
end of what is shown, never shown anew. What went wrong is told under it. Keys
typed in it stay in it: none reaches the editor around it."""

from typing import Optional

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.models.hints import Request

PLACEHOLDER = "Code to write here, in words (Enter asks, Esc closes)"
CLOSE_TIP = "Close (Esc): a question on its way is dropped"
THOUGHT = "Thought"
WIDTH = 520
PREVIEW_LINES = 12  # of the code as it comes; then it follows its end
THOUGHT_LINES = 6  # of the thought, opened
LEAST_LINES = 2  # of the preview, however little room the editor has
GAP = 2  # between the line of the cursor and the box


class Growing(QPlainTextEdit):
    """A text the box shows as it comes: read only, never focused. More of it
    goes at its end, laid out alone; the end stays in sight unless the
    person scrolled up to read."""

    def __init__(self, wrapped: bool, colour: str):
        super().__init__()
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if wrapped else QPlainTextEdit.NoWrap
        )
        self.setStyleSheet(f"color: {colour}; background: {theme.BASE};")
        self._follow = True
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self._grown)
        bar.valueChanged.connect(self._scrolled)
        self.hide()

    def add(self, text: str) -> None:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)

    def restart(self) -> None:
        """Empty, its end followed."""
        self.clear()
        self._follow = True

    def lines_high(self, lines: int) -> int:
        """The height that shows so many lines."""
        margins = 2 * (self.frameWidth() + round(self.document().documentMargin()))
        return lines * self.fontMetrics().lineSpacing() + margins

    def _grown(self, _low: int, high: int) -> None:
        if self._follow:
            self.verticalScrollBar().setValue(high)

    def _scrolled(self, value: int) -> None:
        self._follow = value == self.verticalScrollBar().maximum()


class AskBox(QFrame):
    asked = Signal(str)
    closed = Signal()  # by Esc or ✕: a question on its way is dropped

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("ask_box")
        self.setStyleSheet(
            f"#ask_box {{ background: {theme.PANEL};"
            f" border: 1px solid {theme.ACCENT}; border-radius: 4px; }}"
        )
        self.request: Optional[Request] = None  # the question it follows
        self.caret = QRect()  # the cursor it opened at, in its parent
        self._lines = 0  # of the preview, shown
        self.ticker = QTimer(self)  # the seconds of the question, while it runs
        self.ticker.setInterval(1000)
        self.ticker.timeout.connect(self._tick)
        column = QVBoxLayout(self)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(2)
        column.addLayout(self._field_row())
        column.addLayout(self._progress_row())
        self.thoughtButton = QToolButton()
        self.thoughtButton.setText(THOUGHT)
        self.thoughtButton.setCheckable(True)
        self.thoughtButton.setAutoRaise(True)
        self.thoughtButton.setFocusPolicy(Qt.NoFocus)
        self.thoughtButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.thoughtButton.toggled.connect(self._fold)
        self.thoughtView = Growing(True, theme.MUTED)
        self.thoughtView.setFixedHeight(self.thoughtView.lines_high(THOUGHT_LINES))
        self.preview = Growing(False, theme.TEXT)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        column.addWidget(self.thoughtButton, 0, Qt.AlignLeft)
        column.addWidget(self.thoughtView)
        column.addWidget(self.preview)
        column.addWidget(self.status)
        self._fold(False)
        self.hide()

    def _field_row(self) -> QHBoxLayout:
        self.field = QLineEdit()
        self.field.setPlaceholderText(PLACEHOLDER)
        self.field.addAction(
            theme.icon("creation", theme.ACCENT), QLineEdit.LeadingPosition
        )
        self.closeButton = QToolButton()
        self.closeButton.setAutoRaise(True)
        self.closeButton.setFocusPolicy(Qt.NoFocus)
        self.closeButton.setIcon(theme.icon("close", theme.MUTED))
        self.closeButton.setToolTip(CLOSE_TIP)
        self.closeButton.clicked.connect(self.close_box)
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addWidget(self.field, 1)
        row.addWidget(self.closeButton)
        return row

    def _progress_row(self) -> QHBoxLayout:
        self.spinner = QToolButton()
        self.spinner.setAutoRaise(True)
        self.spinner.setFocusPolicy(Qt.NoFocus)
        self._spin = theme.Spinner(self.spinner)
        self.spinner.setIcon(self._spin.icon)
        self.doing = QLabel()
        self.doing.setStyleSheet(f"color: {theme.ACCENT};")
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.spinner)
        row.addWidget(self.doing, 1)
        self._show_running(False)
        return row

    # Opened
    def open(self, caret: QRect) -> None:
        """At the line of the cursor (caret, in the parent), for words to
        type; what it showed before goes."""
        self.caret = QRect(caret)
        x = max(0, caret.left() - 4)
        self.setFixedWidth(max(0, min(WIDTH, self.parentWidget().width() - x - 8)))
        self.move(x, self.y())
        self.field.setReadOnly(False)
        self.status.hide()
        self._clear()
        self.show()
        self.raise_()
        self._place()
        self.field.setFocus()
        self.field.selectAll()

    def _ask(self) -> None:
        asked = self.field.text().strip()
        if asked and not self.field.isReadOnly():
            self.field.setReadOnly(True)
            self.asked.emit(asked)

    def follow(self, request: Request) -> None:
        """Show what the question does until it ends: what it asks in the
        field, its progress below."""
        self.request = request
        self.field.setText(request.asked)
        self.field.setReadOnly(True)
        self.status.hide()
        self._clear()
        for shown in (self.spinner, self.doing):
            shown.setToolTip(request.server)
        self._show_running(True)
        request.progressed.connect(self._progressed)
        request.ended.connect(self._ended)
        self._tick()
        self._place()

    def tell(self, text: str) -> None:
        """What went wrong: the field takes words again."""
        self.field.setReadOnly(False)
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.BAD};")
        self.status.show()
        self._place()

    def close_box(self) -> None:
        self.hide()
        self.closed.emit()

    # The question followed
    def _progressed(self, thought: str, text: str) -> None:
        if thought:
            self.thoughtView.add(thought)
            if self.thoughtButton.isHidden():
                self.thoughtButton.show()
                self._place()
        if text:
            self.preview.add(text)
            self.preview.show()
            self._fit_preview()
        self._tick()

    def _tick(self) -> None:
        request = self.request
        if request is not None:
            self.doing.setText(
                " · ".join(filter(None, (request.doing(), request.model)))
            )

    def _ended(self) -> None:
        self.request = None
        self._show_running(False)
        self._place()

    def _show_running(self, on: bool) -> None:
        self._spin.run(on)
        self.spinner.setVisible(on)
        self.doing.setVisible(on)
        if on:
            self.ticker.start()
        else:
            self.ticker.stop()

    def _clear(self) -> None:
        """No thought and no code shown: a new question begins."""
        self.thoughtView.restart()
        self.thoughtButton.setChecked(False)
        self.thoughtButton.hide()
        self.preview.restart()
        self.preview.hide()
        self._lines = 0

    def _fold(self, opened: bool) -> None:
        self.thoughtView.setVisible(opened)
        self.thoughtButton.setIcon(
            theme.icon("chevron-down" if opened else "chevron-right", theme.MUTED)
        )
        if self.isVisible():
            self._place()

    def _fit_preview(self) -> None:
        """As high as its lines, up to PREVIEW_LINES: placed anew only when a
        line was added."""
        lines = min(self.preview.document().blockCount(), PREVIEW_LINES)
        if lines != self._lines:
            self._lines = lines
            self._place()

    def _place(self) -> None:
        """Under the line of the cursor when it fits in the parent, else over
        it; a preview too high for the parent shows fewer lines."""
        room = self.parentWidget().height()
        high = self.preview.lines_high(self._lines)
        self.preview.setFixedHeight(high)
        self.adjustSize()
        over = self.height() - room
        if over > 0 and self.preview.isVisible():
            least = self.preview.lines_high(min(self._lines, LEAST_LINES))
            self.preview.setFixedHeight(max(least, high - over))
            self.adjustSize()
        y = self.caret.bottom() + GAP
        if y + self.height() > room:
            y = max(0, self.caret.top() - GAP - self.height())
        self.move(self.x(), y)

    def keyPressEvent(self, event) -> None:
        """What the field leaves (Enter, Esc, keys while it is read only):
        taken here, never passed on to the editor."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._ask()
        elif event.key() == Qt.Key_Escape:
            self.close_box()
        event.accept()
