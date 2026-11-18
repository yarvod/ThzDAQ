"""The person's instructions to the assistant, a page of its settings: an editor
with Save and Revert (back to what is saved), and below it, folded, the
built-in prompt they add to, read only. A view of InstructionsModel."""

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.prompt import built_in
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.models.assistant import InstructionsModel

ABOUT = (
    "Your instructions to the assistant, the same in every workspace. They add"
    " to its built-in prompt: where they contradict its rules, the rules hold."
    " Codex gets them too, after its own instructions. A change applies from"
    " the next message."
)
EXAMPLE = (
    "e.g. Answer in Russian. Before a sweep longer than ten minutes, say how"
    " long it takes."
)


class InstructionsPage(QWidget):
    def __init__(self, instructions: InstructionsModel, parent=None):
        super().__init__(parent)
        self.instructions = instructions
        about = QLabel(ABOUT)
        about.setProperty("role", "muted")
        about.setWordWrap(True)
        self.editor = QPlainTextEdit(instructions.instructions())
        self.editor.setPlaceholderText(EXAMPLE)
        self.editor.textChanged.connect(self.show_saved)
        self.saveButton = QPushButton(theme.icon("content-save-outline"), "Save")
        self.saveButton.clicked.connect(self.save)
        self.revertButton = QPushButton(theme.icon("undo"), "Revert")
        self.revertButton.setToolTip("Back to the instructions saved")
        self.revertButton.clicked.connect(self.revert)
        actions = QHBoxLayout()
        actions.addWidget(self.saveButton)
        actions.addWidget(self.revertButton)
        actions.addStretch()
        self.builtInView = QPlainTextEdit(built_in())
        self.builtInView.setReadOnly(True)
        self.builtIn = Collapsible("Built-in prompt", expanded=False)
        self.builtIn.set_summary("the role, the rules and how a script measures")
        self.builtIn.addWidget(self.builtInView)

        layout = QVBoxLayout(self)
        layout.addWidget(about)
        layout.addWidget(self.editor)
        layout.addLayout(actions)
        layout.addWidget(self.builtIn)
        instructions.changed.connect(self.show_saved)
        self.show_saved()

    def save(self) -> None:
        self.instructions.set_instructions(self.editor.toPlainText())

    def revert(self) -> None:
        self.editor.setPlainText(self.instructions.instructions())

    def show_saved(self) -> None:
        """Save and Revert only while the editor differs from what is saved."""
        changed = self.editor.toPlainText() != self.instructions.instructions()
        self.saveButton.setEnabled(changed)
        self.revertButton.setEnabled(changed)
