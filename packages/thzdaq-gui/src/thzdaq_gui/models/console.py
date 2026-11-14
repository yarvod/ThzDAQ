"""A Python console of the window: its kernel (thzdaq_gui.kernel), what it was
asked to run and what it answered, the inputs it browses, its completions.

The kernel opens on the window's daemon in its workspace, with that
workspace's Python (thzdaq_api.console), and runs OPENING first (from thzdaq
import *, lab = connect()), again after each restart; code asked for while it
starts runs after that. Restart opens it anew on the daemon, workspace and
Python the window has then: until then a kernel keeps the Python it opened
with.

A block runs on Enter when it is complete as typed (codeop: a statement, or a
block closed by an empty line), else Enter goes on to a new line.

Inputs are IPython's history, one for every console of the program: the last
ones are read as the kernel opens, and each run is added.

The last block that raised is kept with its traceback (failed) until another
runs: the assistant mends it on Fix, told the blocks run before it.
"""

import codeop
import os
import re
from collections import OrderedDict
from typing import List, NamedTuple, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from thzdaq_api import console
from thzdaq_api.errors import LabError

from thzdaq_gui.kernel import Kernel

# States of a console
STARTING, IDLE, BUSY, ENDED = "starting", "idle", "busy", "ended"
HISTORY = 1000  # inputs read as a kernel opens
RECENT = 10  # blocks run that a fix is told of
Completion = Tuple[str, str]  # its text, and what it is (its unit, its range)
CONTROL = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")  # a terminal's code (colours)


def plain(text: str) -> str:
    """Text without the codes of a terminal."""
    return CONTROL.sub("", text)


class Failed(NamedTuple):
    code: str  # the block that raised
    error: str  # its traceback, plain
    before: Tuple[str, ...]  # blocks run before it, the oldest first


def complete_block(code: str) -> bool:
    """Whether code runs as typed: a statement, or a block closed by a line
    left blank (its indent aside). Code Python cannot compile (IPython's
    %magic, several statements, a mistake) runs too: the kernel tells."""
    lines = code.split("\n")
    if len(lines) > 1 and not lines[-1].strip():
        lines[-1] = ""
    try:
        compiled = codeop.compile_command("\n".join(lines), "<console>", "single")
    except (SyntaxError, ValueError, OverflowError):
        return True
    return compiled is not None


class History:
    """Inputs, the oldest first, browsed from the newest back; what was typed
    before browsing comes back after the newest."""

    def __init__(self):
        self.entries: List[str] = []
        self.at: Optional[int] = None  # the entry shown; None: the draft
        self.draft = ""
        self.found: Optional[int] = None  # the entry a search found last

    def add(self, code: str) -> None:
        if code.strip() and (not self.entries or self.entries[-1] != code):
            self.entries.append(code)
        self.at = None

    def read(self, older: List[str]) -> None:
        """Inputs of earlier runs, before those of this one."""
        self.entries = [e for e in older if e.strip()] + self.entries

    def older(self, typed: str) -> Optional[str]:
        """The input before the one shown; None at the oldest."""
        if self.at is None:
            if not self.entries:
                return None
            self.draft, self.at = typed, len(self.entries)
        if self.at == 0:
            return None
        self.at -= 1
        return self.entries[self.at]

    def newer(self) -> Optional[str]:
        """The input after the one shown, then the draft; None when not browsing."""
        if self.at is None:
            return None
        self.at += 1
        if self.at >= len(self.entries):
            self.at = None
            return self.draft
        return self.entries[self.at]

    def start_search(self, typed: str) -> None:
        """typed comes back when the search is given up."""
        self.draft, self.found = typed, None

    def find(self, text: str, older: bool = False) -> Optional[str]:
        """The newest input holding text, or (older) the next one older than
        the one found last; None: none."""
        start = self.found if older and self.found is not None else len(self.entries)
        index = next(
            (i for i in range(start - 1, -1, -1) if text in self.entries[i]), None
        )
        if index is None:
            return None
        self.found = index
        return self.entries[index]

    def end_search(self) -> str:
        """What was typed before the search."""
        self.found = None
        return self.draft


class ConsoleModel(QObject):
    state_changed = Signal(str)
    entered = Signal(str)  # a block sent to run, as it is shown
    printed = Signal(str, str)  # stdout or stderr, text
    shown = Signal(str)  # a result, as text
    raised = Signal(list)  # a traceback's lines, with colours
    told = Signal(str)  # what the console says itself: started, ended
    completed = Signal(list, int, int)  # Completion of each, the span they replace
    input_requested = Signal(str, bool)  # input(): the prompt, whether a password
    failed_changed = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.state = STARTING
        self.waiting: List[str] = []  # asked for while it starts
        self.history = History()
        self.asked: Optional[str] = None  # the completion request answered
        self.histories: Optional[str] = None  # the history request answered
        self.sent: "OrderedDict[str, str]" = OrderedDict()  # recent blocks, by request
        self.failed: Optional[Failed] = None  # the last block, when it raised
        # The session owns it: its thread may outlive this console's tab.
        # Its signals reach methods of this object: queued into the window's
        # thread, and gone with it
        self.kernel = Kernel(parent=session)
        self.kernel.started.connect(self._started)
        self.kernel.failed.connect(self._failed)
        self.kernel.died.connect(self._died)
        self.kernel.busy_changed.connect(self._busy)
        self.kernel.printed.connect(self._printed)
        self.kernel.shown.connect(self._shown)
        self.kernel.raised.connect(self._raised)
        self.kernel.completed.connect(self._completed)
        self.kernel.history_found.connect(self._history_found)
        self.kernel.input_requested.connect(self._input_requested)
        try:
            self.kernel.start(*self._place())
        except LabError as e:  # the workspace names a Python that is not there
            self._failed(str(e))

    def _place(self):
        """Where its kernel runs: the window's daemon and workspace now, with
        that workspace's Python; LabError when it names one not there."""
        folder = self.session.workspace.folder
        command = console.kernel_command(folder)
        added = console.kernel_environment(self.session.simulate, folder)
        return command, {**os.environ, **added}, folder

    def _set(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)

    # Its kernel
    def _started(self) -> None:
        self._set(IDLE)
        if self.histories is None:  # once: later runs are added as they go
            self.histories = self.kernel.history(HISTORY)
        self._send(console.OPENING, history=False)
        waiting, self.waiting = self.waiting, []
        for code in waiting:
            self._send(code)

    def _failed(self, why: str) -> None:
        self._set(ENDED)
        self.told.emit(f"The kernel did not start: {why}")

    def _died(self, how: str) -> None:
        self._set(ENDED)
        self.told.emit(f"The kernel ended ({how}): Restart starts a new one")

    def _busy(self, busy: bool) -> None:
        if self.state in (IDLE, BUSY):
            self._set(BUSY if busy else IDLE)

    def _printed(self, _id: str, name: str, text: str) -> None:
        self.printed.emit(name, text)

    def _shown(self, _id: str, text: str) -> None:
        self.shown.emit(text)

    def _raised(self, id: str, lines: list) -> None:
        self.raised.emit(lines)
        if id in self.sent:
            ids = list(self.sent)
            before = tuple(self.sent[i] for i in ids[: ids.index(id)])
            self.failed = Failed(self.sent[id], plain("\n".join(lines)), before)
            self.failed_changed.emit()

    def _input_requested(self, prompt: str, password: bool) -> None:
        self.input_requested.emit(prompt, password)

    def interrupt(self) -> None:
        """What runs gets KeyboardInterrupt, as Ctrl+C in a terminal."""
        self.kernel.interrupt()

    def restart(self) -> None:
        """A new kernel, its names gone; a measurement of the old one ends
        interrupted (its devices restored)."""
        try:
            place = self._place()
        except LabError as e:  # the kernel that runs stays
            self.told.emit(f"Not restarted: {e}")
            return
        self._set(STARTING)
        self.told.emit("Restarting…")
        self.kernel.restart(*place)

    def stop(self) -> None:
        """Its kernel ends (the console's tab closed)."""
        self._set(ENDED)
        self.kernel.stop()

    # Running
    def run(self, code: str) -> None:
        """Run a block; while the kernel starts, once it has opened."""
        self.history.add(code)
        if self.state == STARTING:
            self.waiting.append(code)
        elif self.state != ENDED:
            self._send(code)

    def _send(self, code: str, history: bool = True) -> None:
        self.entered.emit(code)
        id = self.kernel.execute(code, history)
        if not history:
            return  # the opening: not the person's
        self.sent[id] = code
        while len(self.sent) > RECENT:
            self.sent.popitem(last=False)
        if self.failed is not None:
            self.failed = None
            self.failed_changed.emit()

    def answer(self, text: str) -> None:
        """What input() asked for."""
        self.kernel.answer(text)

    # Completions and history
    def complete(self, code: str, cursor: int) -> None:
        """Asked of the kernel: completed tells, for the last one asked."""
        if self.state in (IDLE, BUSY):
            self.asked = self.kernel.complete(code, cursor)

    def _completed(self, id: str, found: list, start: int, end: int) -> None:
        if id == self.asked:
            self.completed.emit(found, start, end)

    def _history_found(self, id: str, inputs: list) -> None:
        if id == self.histories:
            self.history.read(inputs)
