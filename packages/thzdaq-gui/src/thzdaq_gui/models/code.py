"""A script open in the window: its file as saved (or a text a measurement
kept), what it is to the bench, its check, its completions, its last run's
output, and changes made to its file from outside (VS Code, an agent).

A script of the bench's library (one of its own measurements, custom.<name>)
is saved through the daemon (write_custom), which describes it at once and
tells every client; a script of the workspace is written as a file. A text
without a file is saved into the library under a name.

Completions are jedi's (Python and the thzdaq module the script imports)
with the bench's first: devices in lab["…"], and after the dot of a device
(declared or lab["ref"]) its quantities and actions.
"""

import re
from pathlib import Path
from typing import Iterable, List, Optional

import jedi
from PySide6.QtCore import QFileSystemWatcher, QObject, Signal
from thzdaq_api.custom import (
    CheckCustom,
    CustomCheck,
    WriteCustom,
    procedure_name,
)
from thzdaq_api.measurements import SlotInfo

from thzdaq_gui.models.scripts import ScriptRun, ScriptsModel

LIBRARY_CALLS = "library"  # the lane of saves and checks
# lab["sis_bi| (the cursor at |): a device's ref is typed
REF_TYPED = re.compile(r"""\[\s*["'](\w*)$""")
# bias.vol|: a quantity or action of what bias is
ATTRIBUTE_TYPED = re.compile(r"(\w+)\.(\w*)$")
ASSIGNED_REF = r"""^{}\s*=\s*\w+\[\s*["'](\w+)["']\s*\]"""
ASSIGNED_SLOT = r"^{}\s*=\s*device\((.*)\)"
KIND = re.compile(r"""kind\s*=\s*["'](\w+)["']""")
CAPABILITY = re.compile(r"""["']([A-Z]\w+)["']""")


class CodeModel(QObject):
    saved = Signal()  # the text is its file's now
    checked = Signal(object)  # CustomCheck
    disk_changed = Signal(str)  # its file changed outside: the text there
    failed = Signal(str)
    printed = Signal(str)  # more of what its last run printed
    output_reset = Signal(str)  # all its last run printed

    def __init__(
        self,
        session,
        path: Optional[Path],
        text: str,
        title: str,
        parent=None,
    ):
        """path: its file (None: a text a measurement kept, title its name)."""
        super().__init__(parent)
        self.session = session
        self.path = path
        self.saved_text = text
        self.title = title
        self.script = self._library_name()
        self.shown: Optional[int] = None  # the run whose output is shown
        self.scripts: ScriptsModel = session.scripts
        self.scripts.runs_changed.connect(self._follow)
        self.scripts.printed.connect(self._printed)
        self.scripts.output_reset.connect(self._reset)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._file_changed)
        if path is not None:
            self.watcher.addPath(str(path))
        self._follow()

    @classmethod
    def of_file(cls, session, path: Path, parent=None) -> "CodeModel":
        """OSError when it cannot be read."""
        return cls(session, path, path.read_text(encoding="utf-8"), path.name, parent)

    def _library_name(self) -> Optional[str]:
        """Its name in the bench's library, when it is one of its scripts."""
        if self.path is None:
            return None
        folder = Path(self.session.library().folder)
        return self.path.stem if self.path.parent == folder else None

    @property
    def procedure(self) -> Optional[str]:
        """custom.<name> for a script of the library."""
        return None if self.script is None else procedure_name(self.script)

    @property
    def check_name(self) -> str:
        """The name it is checked as."""
        if self.script is not None:
            return self.script
        stem = Path(self.title).stem
        return re.sub(r"\W", "_", stem) or "script"

    def dirty(self, text: str) -> bool:
        return text != self.saved_text

    # Saving and checking
    def save(self, text: str) -> None:
        """Into its file: a script of the library through the daemon (its
        check comes with it), another as a file. A text without a file is
        saved with save_to_library."""
        if self.path is None:
            raise ValueError("a text without a file is saved into the library")
        if self.script is None:
            self.path.write_text(text, encoding="utf-8")
            self._saved(text)
            self.check(text)
            return
        lab, write = self.session.lab, WriteCustom(script=self.script, text=text)
        self.session.calls.submit(
            lambda: lab.call(write),
            lambda checked: self._written(text, checked),
            self._failed,
            key=LIBRARY_CALLS,
        )

    def _written(self, text: str, checked: CustomCheck) -> None:
        self._saved(text)
        self.checked.emit(checked)

    def _saved(self, text: str) -> None:
        self.saved_text = text
        self.saved.emit()

    def check(self, text: str) -> None:
        lab, check = self.session.lab, CheckCustom(script=self.check_name, text=text)
        self.session.calls.submit(
            lambda: lab.call(check), self.checked.emit, self._failed, key=LIBRARY_CALLS
        )

    def _failed(self, error: BaseException) -> None:
        self.failed.emit(str(error))

    # Its file, changed outside
    def _file_changed(self, path: str) -> None:
        # An editor that saves by replacing the file takes it from the watcher
        if path not in self.watcher.files() and Path(path).exists():
            self.watcher.addPath(path)
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            return  # gone, or being replaced: the next change tells
        if text != self.saved_text:
            self.disk_changed.emit(text)

    def take(self, text: str) -> None:
        """The text on disk is the one held from now on (reloaded)."""
        self.saved_text = text

    # Completions
    def complete(self, text: str, line: int, column: int) -> List[str]:
        """The bench's words first, then jedi's."""
        before = text.splitlines()[line - 1][:column] if text else ""
        found = list(self._bench_words(text, before))
        found += [w for w in self._jedi_words(text, line, column) if w not in found]
        return found

    def _bench_words(self, text: str, before: str) -> Iterable[str]:
        if REF_TYPED.search(before):
            return [device.ref for device in self.session.devices()]
        typed = ATTRIBUTE_TYPED.search(before)
        if typed is None:
            return []
        words: List[str] = []
        for ref in self.devices_of(typed[1], text):
            described = self.session.description(ref)
            for word in [q.key for q in described.quantities] + [
                a.key for a in described.actions
            ]:
                if word not in words:
                    words.append(word)
        return words

    def devices_of(self, name: str, text: str) -> List[str]:
        """The devices a name of the script may be: lab["ref"], or the
        devices a declared slot offers."""
        named = re.escape(name)
        found = re.search(ASSIGNED_REF.format(named), text, re.MULTILINE)
        if found is not None:
            return [found[1]]
        slot = re.search(ASSIGNED_SLOT.format(named), text, re.MULTILINE)
        if slot is None:
            return []
        kind = KIND.search(slot[1])
        offered = SlotInfo(
            name, name, tuple(CAPABILITY.findall(slot[1])), kind[1] if kind else None
        )
        return [d.ref for d in offered.candidates(self.session.devices())]

    def _jedi_words(self, text: str, line: int, column: int) -> List[str]:
        script = jedi.Script(text, path=str(self.path) if self.path else None)
        try:
            found = script.complete(line, column)
        except ValueError:  # a position past the text, as it is being typed
            return []
        return [c.name for c in found if not c.name.startswith("__")]

    # Its last run
    def _follow(self) -> None:
        """The newest run of its file: its output is shown."""
        run = None if self.path is None else self.scripts.last_run_of(self.path)
        if run is None or run.id == self.shown:
            return
        self.shown = run.id
        self.output_reset.emit(self.scripts.output(run.id))

    def last_run(self) -> Optional[ScriptRun]:
        return None if self.shown is None else self.scripts.runs.get(self.shown)

    def _printed(self, id: int, text: str) -> None:
        if id == self.shown:
            self.printed.emit(text)

    def _reset(self, id: int) -> None:
        if id == self.shown:
            self.output_reset.emit(self.scripts.output(id))

    def stop(self) -> None:
        """Stop its last run's script (a run of a measurement through its dock)."""
        run = self.last_run()
        if run is not None and run.running:
            self.scripts.stop(run.id)
