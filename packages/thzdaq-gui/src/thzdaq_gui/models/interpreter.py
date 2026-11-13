"""The Python of the window's workspace (thzdaq_api.interpreters): the one
its scripts, its measurements of the bench's own and its consoles run with.

The environments a person chooses among are found, and a chosen one is
checked, apart from the window: uv and conda list theirs and an interpreter
starts in seconds. A check answered after another was asked is told with the
environment it was asked of, so a view shows only the one chosen now. The
choice goes into the workspace's thzdaq.toml; whatever starts afterwards
takes it: a script's Run, a measurement of the bench's own, a new console or
a console's Restart (a console that runs keeps its Python until then).
"""

from typing import Optional, Tuple

from PySide6.QtCore import QObject, Signal
from thzdaq_api import interpreters
from thzdaq_api.interpreters import Checked, Environment
from thzdaq_api.workspace import is_workspace, write_python

from thzdaq_gui.workers import DeviceWorker

FINDING, CHECKING = "find", "check"  # lanes: a check does not wait for conda


class InterpreterModel(QObject):
    # The environments found, and the one the workspace's scripts run with
    found = Signal(object, object)  # Tuple[Environment, ...], Optional[Environment]
    checked = Signal(object, object)  # the Environment checked, its Checked
    failed = Signal(str)  # finding failed (a broken thzdaq.toml): why

    def __init__(self, workspace, parent=None):
        """workspace: the window's (thzdaq_gui.workspace.Workspace)."""
        super().__init__(parent)
        self.workspace = workspace
        self.calls = DeviceWorker(self)

    def close(self, timeout: float = 2.0) -> None:
        self.calls.stop(timeout)

    def editable(self) -> bool:
        """A workspace names its Python; the program's own folder has no
        thzdaq.toml, so its scripts run with the program's own."""
        return is_workspace(self.workspace.folder)

    def find(self) -> None:
        folder = self.workspace.folder

        def look() -> Tuple[Tuple[Environment, ...], Optional[Environment]]:
            found = interpreters.environments(folder)
            return found, interpreters.current(found, folder)

        self.calls.submit(
            look, lambda answer: self.found.emit(*answer), self._failed, key=FINDING
        )

    def check(self, environment: Environment) -> None:
        def look() -> Checked:
            if environment.own:
                return interpreters.check_own()
            return interpreters.check(environment.path)

        self.calls.submit(
            look,
            lambda answer: self.checked.emit(environment, answer),
            self._failed,
            key=CHECKING,
        )

    def choose(self, environment: Environment) -> None:
        """Into thzdaq.toml: named relative to the workspace when it is in it;
        LabError when the file cannot take it."""
        folder = self.workspace.folder
        named = "" if environment.own else interpreters.stored(folder, environment.path)
        write_python(folder, named)

    def _failed(self, error: BaseException) -> None:
        self.failed.emit(str(error))
