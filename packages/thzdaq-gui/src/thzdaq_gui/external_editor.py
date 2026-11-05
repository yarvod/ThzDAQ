"""Folders and scripts opened in VS Code, a program apart from this one: the
window's workspace (File menu), a script in its folder, the line of a
traceback (the Scripts dock).

VS Code opens them by its command code (inside its app bundle on macOS when
not in PATH): the folder, with the file at its line. Without it a person
picks the program once (kept in settings); it is given the file, or the
folder."""

import shutil
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from thzdaq_api import host

from thzdaq_gui.settings import EDITOR, settings

MAC_CODE = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
EDITOR_TITLE = "Open in VS Code"


def code_command() -> Optional[str]:
    """VS Code's command, None when it is not installed where it is looked for."""
    found = shutil.which("code")
    if found is not None:
        return found
    if sys.platform == "darwin" and MAC_CODE.exists():
        return str(MAC_CODE)
    return None


def code_arguments(
    folder: Path, file: Optional[Path] = None, line: Optional[int] = None
) -> List[str]:
    """The folder in a window of VS Code, with the file at its line."""
    if file is None:
        return [str(folder)]
    where = f"{file}:{line}" if line else str(file)
    return [str(folder), "--goto", where]


def editor_command(program: str, path: Path) -> List[str]:
    """How a program opens a file or a folder: an app bundle on macOS through
    open."""
    if sys.platform == "darwin" and program.endswith(".app"):
        return ["open", "-a", program, str(path)]
    return [program, str(path)]


class ExternalEditor:
    """Opens in VS Code, or in the program a person chose for it; tells a
    person in parent when it does not start."""

    def __init__(self, parent: QWidget):
        self.parent = parent

    def open(
        self, folder: Path, file: Optional[Path] = None, line: Optional[int] = None
    ) -> None:
        code = code_command()
        if code is not None:
            command = [code, *code_arguments(folder, file, line)]
        else:
            program = self.chosen()
            if program is None:
                return
            command = editor_command(program, file or folder)
        try:
            host.start_apart(command)
        except OSError as e:
            settings().remove(EDITOR)  # asked again next time
            QMessageBox.warning(self.parent, EDITOR_TITLE, f"{command[0]}: {e}")

    def chosen(self) -> Optional[str]:
        """The program a person chose for want of VS Code (asked once)."""
        chosen = settings().value(EDITOR)
        if chosen and Path(chosen).exists():
            return chosen
        chosen, _ = QFileDialog.getOpenFileName(
            self.parent, "VS Code is not found: the editor to open scripts with"
        )
        if not chosen:
            return None
        settings().setValue(EDITOR, chosen)
        return chosen
