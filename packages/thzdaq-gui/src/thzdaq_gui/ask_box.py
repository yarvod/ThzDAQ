"""The small field Ctrl+I opens in an editor, under the line of the cursor:
the person says in words what code to write there; Enter asks, Esc closes
(and drops a question on its way). While the assistant writes it says so;
what went wrong is told under the words. Keys typed in it stay in it: none
reaches the editor around it."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QVBoxLayout, QWidget

from thzdaq_gui import theme

PLACEHOLDER = "Code to write here, in words (Enter asks, Esc closes)"
WRITING = "The assistant writes…"
WIDTH = 520


class AskBox(QFrame):
    asked = Signal(str)
    closed = Signal()  # by Esc: a question on its way is dropped

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("ask_box")
        self.setStyleSheet(
            f"#ask_box {{ background: {theme.PANEL};"
            f" border: 1px solid {theme.ACCENT}; border-radius: 4px; }}"
        )
        column = QVBoxLayout(self)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(2)
        self.field = QLineEdit()
        self.field.setPlaceholderText(PLACEHOLDER)
        self.field.addAction(
            theme.icon("creation", theme.ACCENT), QLineEdit.LeadingPosition
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        column.addWidget(self.field)
        column.addWidget(self.status)
        self.hide()

    def open(self, x: int, y: int, width: int) -> None:
        self.field.setReadOnly(False)
        self.status.hide()
        self.setFixedWidth(min(WIDTH, width))
        self.adjustSize()
        self.move(x, y)
        self.show()
        self.raise_()
        self.field.setFocus()
        self.field.selectAll()

    def _ask(self) -> None:
        asked = self.field.text().strip()
        if asked and not self.field.isReadOnly():
            self.field.setReadOnly(True)
            self.tell(WRITING, theme.MUTED)
            self.asked.emit(asked)

    def tell(self, text: str, colour: str = theme.BAD) -> None:
        """What happens, or went wrong: the field takes words again after a
        failure."""
        self.field.setReadOnly(colour == theme.MUTED)
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour};")
        self.status.show()
        self.adjustSize()

    def keyPressEvent(self, event) -> None:
        """What the field leaves (Enter, Esc, keys while it is read only):
        taken here, never passed on to the editor."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._ask()
        elif event.key() == Qt.Key_Escape:
            self.hide()
            self.closed.emit()
        event.accept()
