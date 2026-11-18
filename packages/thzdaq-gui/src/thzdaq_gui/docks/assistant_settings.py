"""The assistant's settings: its pages as tabs, each a view of its own model
(model servers, the person's instructions, Codex)."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QVBoxLayout

from thzdaq_gui.assistant.codex import TITLE as CODEX
from thzdaq_gui.docks.codex_settings import CodexPage
from thzdaq_gui.docks.instructions import InstructionsPage
from thzdaq_gui.docks.providers import ProvidersPage
from thzdaq_gui.models.assistant import (
    CodexSettingsModel,
    InstructionsModel,
    ProvidersModel,
)

TITLE = "Assistant settings"
SERVERS = "Model servers"
INSTRUCTIONS = "Instructions"


class AssistantSettings(QDialog):
    def __init__(
        self,
        providers: ProvidersModel,
        instructions: InstructionsModel,
        codex: CodexSettingsModel,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.resize(720, 480)
        self.servers = ProvidersPage(providers)
        self.instructions = InstructionsPage(instructions)
        self.codex = CodexPage(codex)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.servers, SERVERS)
        self.tabs.addTab(self.instructions, INSTRUCTIONS)
        self.tabs.addTab(self.codex, CODEX)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(close)
