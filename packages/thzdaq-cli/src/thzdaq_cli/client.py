"""What a command works with: the daemon (started when none runs), its
workspace, questions in the terminal, output as text or JSON, and the exit
codes.

The workspace is the folder given with --workspace, else the nearest one from
here up (thzdaq.toml), else none: the daemon writes to the program's. A daemon
the command starts loads the profile that workspace expects."""

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from thzdaq_api import host
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Lab
from thzdaq_api.operation import Operation
from thzdaq_api.origins import AGENT_CLI, CLI, agent_shell
from thzdaq_api.terminal import yes
from thzdaq_api.station import GetStation
from thzdaq_api.workspace import (
    chosen,
    expected_profile,
    profile_name,
    profile_warning,
)

from thzdaq_cli import show

R = TypeVar("R")
PROG = "thzdaq"  # the command, as people type it
KIND = CLI
OK, FAILED, USAGE, NO_DAEMON = 0, 1, 2, 3
# How --workspace defaults, as its help says
HERE = "default: the workspace here or above, else the program's"
THIS_FOLDER = "default: this folder"  # of a command that writes into a folder


def origin() -> str:
    """cli in a person's terminal, cli:agent in an agent's shell: what it
    changes waits for a person in the window."""
    return AGENT_CLI if agent_shell() else CLI


class Mistyped(Exception):
    """What was typed does not fit (exit 2, as argparse does)."""


# The lab of the bench, or of its simulator, listened to as a kind of client;
# started when none runs (autostart) with a profile (station)
Connect = Callable[[bool, bool, str, Optional[str]], Lab]


def reach(simulate: bool, autostart: bool, kind: str, station: Optional[str]) -> Lab:
    """The running daemon; started when none runs and autostart allows it."""
    try:
        return host.connect(simulate, origin(), kind)
    except LabError as e:
        if e.code != ErrorCode.UNREACHABLE or not autostart:
            raise
    lab = host.connect_or_start(simulate, station, origin(), kind)
    print(f"daemon started (pid {lab.host.pid})", file=sys.stderr)
    return lab


class Client:
    """What a command works with: the lab, questions in the terminal, output."""

    def __init__(self, args: argparse.Namespace, connect: Connect):
        self.simulate: bool = args.simulate
        self.json: bool = args.json
        self.yes: bool = args.yes
        self.autostart: bool = not args.no_autostart
        self.kind: str = args.kind  # cli; cli:answers while a person answers here
        self.workspace: Optional[Path] = chosen(args.workspace)
        self._connect = connect
        self._lab: Optional[Lab] = None

    @property
    def lab(self) -> Lab:
        if self._lab is None:
            self._lab = self._connect(
                self.simulate,
                self.autostart,
                self.kind,
                expected_profile(self.workspace),
            )
        return self._lab

    def running_lab(self) -> Lab:
        """The daemon only when it runs already: LabError UNREACHABLE otherwise."""
        if self._lab is None:
            self._lab = self._connect(self.simulate, False, self.kind, None)
        return self._lab

    def daemons_profile(self) -> str:
        """The name of the profile the running daemon works with; none when no
        daemon runs (none is started for it)."""
        try:
            path = self.running_lab().call(GetStation()).path
        except LabError as e:
            if e.code != ErrorCode.UNREACHABLE:
                raise
            return ""
        return profile_name(path) if path else ""

    def folder(self) -> Optional[str]:
        """The workspace as operations name it (None: the program's); a
        person is warned when it expects another profile than the daemon's."""
        warning = profile_warning(self.lab, self.workspace)
        if warning:
            print(f"{PROG}: {warning}", file=sys.stderr)
        return str(self.workspace) if self.workspace else None

    def call(self, operation: Operation[R]) -> R:
        return self.lab.call(operation)

    def ask(self, question: str) -> bool:
        """yes or no in the terminal; --yes answers yes, no terminal answers no."""
        if self.yes:
            return True
        if not sys.stdin.isatty():
            print(f"{question} — not asked without a terminal: --yes", file=sys.stderr)
            return False
        return yes(input(f"{question} [y/N] "))

    def shared(self, call: Callable[[bool], R]) -> Optional[R]:
        """call(share=False); a conflict (a device another measurement sweeps)
        is asked, and on yes called again with share. None when not."""
        try:
            return call(False)
        except LabError as e:
            if e.code != ErrorCode.CONFLICT:
                raise
            if not self.ask(f"{e.message}. Go on anyway (both note it)?"):
                return None
        return call(True)

    def out(self, value: Any, human: Callable[[Any], str]) -> None:
        print(show.as_json(value) if self.json else human(value))
