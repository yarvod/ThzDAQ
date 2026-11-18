"""Codex in the assistant's dock, a page of its settings: the adapter's
command line (codex-acp from npm unless another is set), the codex it runs
(CODEX_PATH; empty: the adapter's own), the mode a new chat starts in, and
Test, which starts the adapter in the background and initializes it only,
telling the versions found or what is wrong. Save keeps them; a new chat
starts with them. A view of CodexSettingsModel."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.codex import ADAPTER, COMMAND, MODES
from thzdaq_gui.models.assistant import CodexSettingsModel

ABOUT = (
    "Codex answers here through its ACP adapter, in the workspace's folder, and"
    " reaches the bench through thzdaq mcp: what it changes there waits for you"
    " in the window; what it runs or writes on its own it asks you first. Sign"
    " in once with `codex login` in a terminal: the program never takes keys."
)
TESTING = "Starting the adapter…"
SAVED = "Saved: a new chat starts with it."


class CodexPage(QWidget):
    def __init__(self, codex: CodexSettingsModel, parent=None):
        super().__init__(parent)
        self.codex = codex
        about = QLabel(ABOUT)
        about.setProperty("role", "muted")
        about.setWordWrap(True)
        self.command = QLineEdit(codex.command())
        self.command.setPlaceholderText(COMMAND)
        self.command.setToolTip(
            f"How the adapter starts: {ADAPTER} from npm by default, or its own"
            " path; npx must be on the program's PATH"
        )
        self.executable = QLineEdit(codex.executable())
        self.executable.setPlaceholderText("the adapter's own")
        self.executable.setToolTip(
            "The codex the adapter runs (CODEX_PATH), e.g. the Codex CLI you"
            " signed in with"
        )
        self.mode = QComboBox()
        for mode in MODES:
            self.mode.addItem(mode.title, mode.id)
            self.mode.setItemData(self.mode.count() - 1, mode.tip, Qt.ToolTipRole)
        self.mode.setCurrentIndex(self.mode.findData(codex.mode()))
        form = QFormLayout()
        form.addRow("Adapter", self.command)
        form.addRow("Codex", self.executable)
        form.addRow("Mode of a new chat", self.mode)
        self.testButton = QPushButton(theme.icon("lan-check"), "Test")
        self.testButton.setToolTip("Start the adapter and ask its version")
        self.testButton.clicked.connect(self.test)
        self.saveButton = QPushButton(theme.icon("content-save-outline"), "Save")
        self.saveButton.clicked.connect(self.save)
        actions = QHBoxLayout()
        actions.addWidget(self.testButton)
        actions.addWidget(self.saveButton)
        actions.addStretch()
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout = QVBoxLayout(self)
        layout.addWidget(about)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.result)
        layout.addStretch()
        codex.tested.connect(self.show_test)

    def test(self) -> None:
        self.testButton.setEnabled(False)
        self.show_result(True, TESTING)
        self.codex.test(self.command.text(), self.executable.text())

    def show_test(self, works: bool, told: str) -> None:
        self.testButton.setEnabled(True)
        self.show_result(works, told)

    def save(self) -> None:
        self.codex.save(
            self.command.text(), self.executable.text(), self.mode.currentData()
        )
        self.command.setText(self.codex.command())
        self.show_result(True, SAVED)

    def show_result(self, works: bool, text: str) -> None:
        self.result.setStyleSheet(f"color: {theme.GOOD if works else theme.BAD};")
        self.result.setText(text)
