from PySide6 import QtGui
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSpinBox


class SpinBox(QSpinBox):
    def __init__(self, parent, btn_return_method=None):
        super().__init__(parent)
        self.btn_return_method = btn_return_method
        # Set focus policy to click focus
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def textFromValue(self, value):
        # show + sign for positive values
        text = super().textFromValue(value)
        if value >= 0:
            text = "+" + text
        return text

    def stepBy(self, steps):
        # Change single step and perform the step
        super().stepBy(steps)
        # Undo selection of the whole text.
        self.lineEdit().deselect()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Return:
            if callable(self.btn_return_method):
                self.btn_return_method()

        super().keyPressEvent(event)

    def wheelEvent(self, event):
        # Process wheel event only if the spinbox has focus
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()
