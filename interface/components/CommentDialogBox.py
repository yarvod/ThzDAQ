from PyQt5.QtWidgets import (
    QVBoxLayout,
    QPlainTextEdit,
    QDialog,
    QHBoxLayout,
)

from interface.components.ui.Button import Button


class CommentDialogBox(QDialog):
    def __init__(self, parent, comment: str):
        super().__init__(parent)
        self.setWindowTitle("Edit Comment")

        self.commentEdit = QPlainTextEdit(self)
        self.commentEdit.setPlainText(comment)

        self.btnSave = Button(self)
        self.btnSave.setText("Save")
        self.btnSave.clicked.connect(self.accept)

        self.btnClose = Button(self)
        self.btnClose.setText("Close")
        self.btnClose.clicked.connect(self.reject)

        layout = QVBoxLayout()
        comment_layout = QVBoxLayout()
        buttons_layout = QHBoxLayout()
        comment_layout.addWidget(self.commentEdit)
        buttons_layout.addWidget(self.btnSave)
        buttons_layout.addWidget(self.btnClose)
        layout.addLayout(comment_layout)
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
