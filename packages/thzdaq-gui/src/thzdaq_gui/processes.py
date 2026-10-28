"""What runs now: measurements, scans in device docks, polling, rotation.

A widget that starts something long registers a Process with the session and
finishes it when it ends; the Processes dock lists them with Stop (and Abort
where the widget offers it) and brings the widget's dock to the front. The
widget stays the owner: a Process only calls back into it.
"""

import logging
import time
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

Action = Callable[[], None]


class Process(QObject):
    changed = Signal()

    def __init__(
        self,
        title: str,
        icon: str,
        dock: str,
        stop: Action,
        abort: Optional[Action] = None,
        reveal: Optional[Action] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.title = title
        self.icon = icon  # mdi6 icon name
        self.dock = dock  # the dock that shows it, e.g. "measure:sis.pv_curve"
        self.reveal = reveal  # after the dock is shown: unfold the scan
        self.status = ""
        self.progress: Optional[Tuple[int, int]] = None  # done, total; None: busy
        self.can_abort = False
        self.started = time.monotonic()
        self._stop = stop
        self._abort = abort

    def update(self, status=None, progress=..., can_abort=None) -> None:
        if status is not None:
            self.status = status
        if progress is not ...:
            self.progress = progress
        if can_abort is not None:
            self.can_abort = can_abort and self._abort is not None
        self.changed.emit()

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def stop(self) -> None:
        self._call(self._stop)

    def abort(self) -> None:
        if self._abort is not None:
            self._call(self._abort)

    def show(self) -> None:
        if self.reveal is not None:
            self._call(self.reveal)

    def _call(self, action: Action) -> None:
        try:
            action()
        except RuntimeError as e:  # the widget behind it is gone
            logger.warning(f"{self.title}: {e}")


class Processes(QObject):
    added = Signal(object)
    removed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[Process] = []

    def start(
        self,
        title: str,
        icon: str,
        dock: str,
        stop: Action,
        abort: Optional[Action] = None,
        reveal: Optional[Action] = None,
    ) -> Process:
        process = Process(title, icon, dock, stop, abort, reveal, self)
        self.items.append(process)
        self.added.emit(process)
        return process

    def finish(self, process: Optional[Process]) -> None:
        if process is None or process not in self.items:
            return
        self.items.remove(process)
        self.removed.emit(process)
        process.deleteLater()

    def stop_all(self) -> None:
        for process in list(self.items):
            process.stop()
