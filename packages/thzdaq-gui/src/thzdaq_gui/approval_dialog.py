"""An agent asks a person: allow an operation (perhaps with another value) or
not, with words the agent reads; or answer its question. One modal dialog at a
time; one answered elsewhere closes."""

from collections import deque
from typing import Deque, Optional

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.approvals import Approval

from thzdaq_gui import theme
from thzdaq_gui.models.approvals import ApprovalsModel


class ApprovalDialog(QDialog):
    def __init__(self, approval: Approval, model: ApprovalsModel, parent=None):
        super().__init__(parent)
        self.approval = approval
        self.model = model
        question = not approval.operation
        self.setWindowTitle("Question" if question else "Allow?")
        self.setWindowIcon(theme.icon("robot-outline"))
        self.setWindowModality(Qt.ApplicationModal)
        layout = QVBoxLayout(self)
        who = QLabel(f"{approval.origin} {'asks' if question else 'wants to'}:")
        who.setProperty("role", "muted")
        title = QLabel(approval.title)
        title.setProperty("role", "title")
        text = QLabel(approval.text)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        for widget in (who, title, text):
            layout.addWidget(widget)
        if approval.warning:
            warning = QLabel(approval.warning)
            warning.setWordWrap(True)
            warning.setStyleSheet(f"color: {theme.ACCENT}")
            layout.addWidget(warning)
        form = QFormLayout()
        self.value: Optional[QLineEdit] = None
        if approval.value is not None:  # the person may set another value
            self.value = QLineEdit(approval.value)
            form.addRow("Value", self.value)
        self.choice: Optional[QComboBox] = None
        if approval.options:
            self.choice = QComboBox()
            self.choice.addItems(approval.options)
            form.addRow("Answer", self.choice)
        self.confirm: Optional[QLineEdit] = None
        if approval.confirm:
            self.confirm = QLineEdit()
            self.confirm.setPlaceholderText(approval.confirm)
            form.addRow(f"Type {approval.confirm}", self.confirm)
        self.words = QLineEdit()
        self.words.setPlaceholderText(
            "your answer" if question else "for the agent: why not, what instead"
        )
        form.addRow("Words", self.words)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setStyleSheet(f"color: {theme.ACCENT}")
        self.status.hide()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox()
        self.allow = buttons.addButton(
            "Answer" if question else "Allow", QDialogButtonBox.AcceptRole
        )
        self.deny = buttons.addButton(
            "Decline" if question else "Deny", QDialogButtonBox.RejectRole
        )
        buttons.accepted.connect(self.allowed)
        buttons.rejected.connect(self.denied)
        layout.addWidget(buttons)
        if self.confirm is not None:
            self.confirm.textChanged.connect(self.check_confirm)
            self.check_confirm()
        model.closed.connect(self.closed_elsewhere)
        model.failed.connect(self.refused)

    def check_confirm(self, *_) -> None:
        """A dangerous step: allowed once its device is typed."""
        self.allow.setEnabled(self.confirm.text().strip() == self.approval.confirm)

    def allowed(self) -> None:
        value = self.value.text().strip() if self.value is not None else None
        self.model.answer(
            self.approval.id,
            True,
            self.words.text().strip(),
            value if value != self.approval.value else None,
            self.choice.currentText() if self.choice is not None else None,
            self.confirm.text().strip() if self.confirm is not None else "",
        )
        self._waiting()

    def denied(self) -> None:
        self.model.answer(self.approval.id, False, self.words.text().strip())
        self._waiting()

    def _waiting(self) -> None:
        """The answer travels; the dialog closes when the daemon closes it."""
        for button in (self.allow, self.deny):
            button.setEnabled(False)

    def closed_elsewhere(self, id: int) -> None:
        if id == self.approval.id:
            self.done(QDialog.Accepted)

    def refused(self, id: int, why: str) -> None:
        """The daemon did not take the answer (a mistyped value): try again."""
        if id != self.approval.id:
            return
        self.status.setText(why)
        self.status.show()
        self.deny.setEnabled(True)
        if self.confirm is not None:
            self.check_confirm()
        else:
            self.allow.setEnabled(True)

    def reject(self) -> None:
        """Escape or the close button answers no: an agent never waits on a
        dialog nobody sees."""
        if self.deny.isEnabled():
            self.denied()


class ApprovalPrompts(QObject):
    """Shows what waits for a person, one dialog at a time, in front."""

    def __init__(self, model: ApprovalsModel, window: QWidget):
        super().__init__(window)
        self.model = model
        self.window = window
        self.queue: Deque[Approval] = deque()
        self.current: Optional[ApprovalDialog] = None
        model.asked.connect(self.asked)

    def asked(self, approval: Approval) -> None:
        self.queue.append(approval)
        self.show_next()

    def show_next(self) -> None:
        if self.current is not None:
            return
        while self.queue:
            approval = self.queue.popleft()
            if approval.id in self.model.pending:
                break
        else:
            return
        self.current = ApprovalDialog(approval, self.model, self.window)
        self.current.finished.connect(self.dismissed)
        self.current.show()
        self.window.raise_()
        self.window.activateWindow()
        QApplication.alert(self.window)  # the taskbar flashes if the window is behind

    def dismissed(self, *_) -> None:
        self.current.deleteLater()
        self.current = None
        self.show_next()
