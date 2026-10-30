"""The daemon the window works with, as it says about itself (get_daemon_status,
asked every couple of seconds): alive, alive with problems, or not answering;
and what a person does with it: restart, stop, kill, start again. The daemon
left at a switch to the simulator (or back) goes on: the exit may stop it too.

Its calls have a queue of their own: a device that hangs does not hold them.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from thzdaq_api import host
from thzdaq_api.daemon import (
    DaemonStatus,
    GetDaemonStatus,
    RestartDaemon,
    StopDaemon,
    StopMode,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Lab
from thzdaq_api.operation import Operation

LOOK_MS = 2000
LANE = "daemon"  # the queue of its calls

CONNECTING, OK, PROBLEMS, LOST = "connecting", "ok", "problems", "lost"


@dataclass(frozen=True)
class LeftDaemon:
    """The daemon left at a switch to the simulator or back: it goes on."""

    simulate: bool  # the simulator's, or the instruments'
    running: int  # measurements it runs
    others: int  # its clients other than this program


class DaemonModel(QObject):
    changed = Signal()  # state, status or why it is lost

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.state = CONNECTING
        self.status: Optional[DaemonStatus] = None
        self.why = ""  # what went wrong when it is lost
        self._asking = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.look)
        self.timer.start(LOOK_MS)
        session.station_changed.connect(self.look)  # another lab: ask at once
        self.look()

    def look(self, *_) -> None:
        if self._asking:
            return
        self._asking = True
        self._call(GetDaemonStatus(), self._heard, self._lost)

    def _heard(self, status: DaemonStatus) -> None:
        self._asking = False
        self.status, self.why = status, ""
        self.state = PROBLEMS if status.problems else OK
        self.changed.emit()

    def _lost(self, error: BaseException) -> None:
        self._asking = False
        self.why = str(error)
        reachable = isinstance(error, LabError) and error.code != ErrorCode.UNREACHABLE
        self.state = PROBLEMS if reachable else LOST
        self.changed.emit()

    def ask(self) -> Optional[DaemonStatus]:
        """The status now, waiting for it; None when the daemon does not answer."""
        status = asked(self.session.lab)
        if status is not None:
            self.status = status
        return status

    # What it serves now
    def others(self) -> int:
        """Clients of the daemon other than this program (another window, a CLI)."""
        return other_clients(self.status)

    # The daemon left at a switch
    def ask_left(self) -> Optional[LeftDaemon]:
        """How it stands now; None when there is none or it ended (idle, stopped)."""
        status = None if self.session.left is None else asked(self.session.left)
        if status is None:
            return None
        return LeftDaemon(
            not self.session.simulate, len(status.runs), other_clients(status)
        )

    def stop_left(self, mode: StopMode) -> None:
        self.session.left.call(StopDaemon(mode=mode))

    def log(self) -> Path:
        return host.DaemonFiles.of(self.session.simulate).log

    # What a person does with it
    def restart(self, mode: StopMode) -> None:
        """It comes back on another port; the window reconnects (resync)."""
        self._call(RestartDaemon(mode=mode), lambda _: self.look(), self._lost)

    def stop(self, mode: StopMode) -> None:
        self._call(StopDaemon(mode=mode), lambda _: self.look(), self._lost)

    def stop_now(self, mode: StopMode) -> None:
        """Stop it before the window goes: waits for its answer."""
        self.session.call(StopDaemon(mode=mode))

    def start(self) -> None:
        """Connect again, starting it when none runs; LabError when it fails."""
        self.session.open(self.session.simulate)
        self.look()

    def kill(self) -> Optional[int]:
        """End a daemon that does not answer; its pid, None when none ran."""
        killed = host.kill(self.session.simulate)
        self.look()
        return killed

    def _call(self, operation: Operation, done, failed) -> None:
        lab = self.session.lab
        self.session.calls.submit(
            lambda: lab.call(operation), done, failed, "daemon", key=LANE
        )


def asked(lab: Lab) -> Optional[DaemonStatus]:
    """A daemon's status, waiting for it; None when it does not answer."""
    try:
        return lab.call(GetDaemonStatus())
    except LabError:
        return None


def other_clients(status: Optional[DaemonStatus]) -> int:
    """Clients of a daemon other than this program (another window, a CLI)."""
    if status is None:
        return 0
    return sum(1 for client in status.clients if client.pid != os.getpid())
