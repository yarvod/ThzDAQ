"""The workspace in the File menu: open one (or a recent one), make a new one,
open it at start, open it in VS Code or in the file manager. A workspace that
expects another profile than the daemon's asks whether to switch the daemon
to it, when it opens (the daemon refuses while measurements run).

VS Code opens a folder by its command code (inside its app bundle on macOS
when not in PATH); without it, a person picks the program once. The files for
agents of a new workspace come from the command line (thzdaq agent-setup),
another program: the window does not import it."""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QToolButton,
    QWidget,
)
from thzdaq_api import host
from thzdaq_api.errors import LabError
from thzdaq_api.workspace import mismatch_text, other_profile, profile_name

from thzdaq_gui import theme
from thzdaq_gui.settings import EDITOR, settings

WORKSPACE = "Workspace"  # the title of its dialogs
OPEN_WORKSPACE = "Open workspace"
FILE_MANAGER = {"win32": "Open in Explorer", "darwin": "Open in Finder"}.get(
    sys.platform, "Open in file manager"
)
MAC_CODE = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
AGENT_SETUP_S = 60.0  # writing the agents' files takes a moment


def code_command() -> Optional[str]:
    """VS Code's command, None when it is not installed where it is looked for."""
    found = shutil.which("code")
    if found is not None:
        return found
    if sys.platform == "darwin" and MAC_CODE.exists():
        return str(MAC_CODE)
    return None


def editor_command(program: str, folder: Path) -> List[str]:
    """How a program opens a folder: an app bundle on macOS through open."""
    if sys.platform == "darwin" and program.endswith(".app"):
        return ["open", "-a", program, str(folder)]
    return [program, str(folder)]


class SetupFailed(Exception):
    """thzdaq agent-setup did not write the agents' files: what it said."""


def write_agent_files(folder: Path, simulate: bool) -> None:
    """What Claude Code and Codex read in folder, as thzdaq agent-setup writes
    it; LabError without the command line, SetupFailed when it fails."""
    command = [
        *host.cli_command(),
        *(["--simulate"] if simulate else []),
        "agent-setup",
        str(folder),
    ]
    done = subprocess.run(
        command, capture_output=True, text=True, timeout=AGENT_SETUP_S
    )
    if done.returncode != 0:
        raise SetupFailed(f"agent-setup failed: {done.stderr.strip()}")


class NewWorkspace(QDialog):
    """Where, which profile it expects, and whether agents work in it."""

    def __init__(self, station: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New workspace")
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("a new or an empty folder")
        browse = QToolButton()
        browse.setIcon(theme.icon("folder-open-outline"))
        browse.setToolTip("Choose the folder")
        browse.clicked.connect(self.browse)
        where = QHBoxLayout()
        where.addWidget(self.folder)
        where.addWidget(browse)
        self.station = QLineEdit(station)
        self.station.setPlaceholderText("none")
        self.station.setToolTip("Its name in the program's stations/")
        self.agents = QCheckBox("Files for agents (Claude Code, Codex)")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow("Folder", where)
        form.addRow("Profile", self.station)
        form.addRow("", self.agents)
        form.addRow(buttons)
        self.resize(520, self.sizeHint().height())

    def browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Folder of the workspace")
        if chosen:
            self.folder.setText(chosen)

    def accept(self) -> None:
        if self.folder.text().strip():
            super().accept()


class WorkspaceMenu(QObject):
    def __init__(self, session, load_profile: Callable[[str], None], window: QWidget):
        """load_profile(name): switch the daemon to a profile, its refusal told."""
        super().__init__(window)
        self.session = session
        self.workspace = session.workspace
        self.load_profile = load_profile
        self.window = window
        self.workspace.changed.connect(self.check_profile)
        self.recentMenu: Optional[QMenu] = None  # in the menu it is added to
        self.atStart = QAction("Open this workspace at start", self)
        self.atStart.setCheckable(True)
        self.atStart.toggled.connect(self.workspace.make_default)

    def add_to(self, menu: QMenu) -> None:
        opening = self._action(f"{OPEN_WORKSPACE}…", "folder-open-outline", self.open)
        opening.setShortcut(QKeySequence("Ctrl+Shift+O"))
        menu.addAction(opening)
        menu.addAction(self._action("New workspace…", "folder-plus-outline", self.new))
        self.recentMenu = menu.addMenu(theme.icon("history"), "Recent workspaces")
        self.recentMenu.aboutToShow.connect(self.fill_recent)
        menu.addAction(self.atStart)
        menu.aboutToShow.connect(self.show_default)
        menu.addAction(
            self._action(
                "Open in VS Code", "microsoft-visual-studio-code", self.open_in_editor
            )
        )
        menu.addAction(
            self._action(FILE_MANAGER, "folder-outline", self.open_in_file_manager)
        )

    def _action(self, text: str, icon_name: str, slot: Callable[[], None]) -> QAction:
        action = QAction(theme.icon(icon_name), text, self)
        action.triggered.connect(slot)
        return action

    def show_default(self) -> None:
        self.atStart.blockSignals(True)
        self.atStart.setChecked(self.workspace.is_default())
        self.atStart.blockSignals(False)

    def fill_recent(self) -> None:
        self.recentMenu.clear()
        others = [f for f in self.workspace.recent() if f != self.workspace.folder]
        for folder in others:
            action = self.recentMenu.addAction(str(folder))
            action.triggered.connect(lambda _=False, f=folder: self.workspace.open(f))
        if not others:
            self.recentMenu.addAction("None yet").setEnabled(False)

    def open(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self.window, OPEN_WORKSPACE, str(self.workspace.folder.parent)
        )
        if chosen:
            self.workspace.open(chosen)

    def new(self) -> None:
        path = self.session.profile().path
        dialog = NewWorkspace(profile_name(path) if path else "", self.window)
        if dialog.exec() != QDialog.Accepted:
            return
        folder = Path(dialog.folder.text().strip()).expanduser()
        try:
            self.workspace.create(folder, dialog.station.text().strip())
            if dialog.agents.isChecked():
                write_agent_files(folder, self.session.simulate)
        except (LabError, SetupFailed, OSError, subprocess.TimeoutExpired) as e:
            QMessageBox.warning(self.window, WORKSPACE, str(e))
            return
        self.workspace.open(folder)

    def check_profile(self) -> None:
        """Asks to switch the daemon when the workspace expects another
        profile."""
        loaded = self.session.profile().path
        try:
            expected = other_profile(self.workspace.folder, loaded)
        except LabError as e:  # its thzdaq.toml is broken
            QMessageBox.warning(self.window, WORKSPACE, str(e))
            return
        if expected is None:
            return
        answer = QMessageBox.question(
            self.window,
            WORKSPACE,
            f"{mismatch_text(expected, loaded)}.\n\nSwitch the daemon to "
            f"{expected!r}? It refuses while measurements run.",
        )
        if answer == QMessageBox.Yes:
            self.load_profile(expected)

    def open_in_editor(self) -> None:
        folder = self.workspace.folder
        code = code_command()
        if code is not None:
            command = [code, str(folder)]
        else:
            program = self.editor()
            if program is None:
                return
            command = editor_command(program, folder)
        try:
            host.start_apart(command)
        except OSError as e:
            settings().remove(EDITOR)  # asked again next time
            QMessageBox.warning(self.window, WORKSPACE, f"{command[0]}: {e}")

    def editor(self) -> Optional[str]:
        """The program a person chose for folders without VS Code (asked once)."""
        chosen = settings().value(EDITOR)
        if chosen and Path(chosen).exists():
            return chosen
        chosen, _ = QFileDialog.getOpenFileName(
            self.window, "VS Code is not found: the editor to open folders with"
        )
        if not chosen:
            return None
        settings().setValue(EDITOR, chosen)
        return chosen

    def open_in_file_manager(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.workspace.folder)))
