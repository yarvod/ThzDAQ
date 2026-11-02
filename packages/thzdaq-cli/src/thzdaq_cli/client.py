"""What a command works with: the daemon (started when none runs), questions
in the terminal, output as text or JSON, and the exit codes."""

import argparse
import os
import sys
from typing import Any, Callable, Optional, TypeVar

from thzdaq_api import host
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Lab
from thzdaq_api.operation import Operation
from thzdaq_api.origins import AGENT_CLI, CLI

from thzdaq_cli import show

R = TypeVar("R")
PROG = "thzdaq"  # the command, as people type it
KIND = CLI
OK, FAILED, USAGE, NO_DAEMON = 0, 1, 2, 3
# Set in the shells agents run commands in (Claude Code, Codex): a command
# there is the agent's, so what it changes waits for a person in the window
AGENT_SHELLS = ("CLAUDECODE", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")


def origin() -> str:
    """cli in a person's terminal, cli:agent in an agent's shell."""
    return AGENT_CLI if any(os.environ.get(name) for name in AGENT_SHELLS) else CLI


class Mistyped(Exception):
    """What was typed does not fit (exit 2, as argparse does)."""


# The lab of the bench, or of its simulator, listened to as a kind of client;
# started when none runs (autostart)
Connect = Callable[[bool, bool, str], Lab]


def reach(simulate: bool, autostart: bool, kind: str) -> Lab:
    """The running daemon; started when none runs and autostart allows it."""
    try:
        return host.connect(simulate, origin(), kind)
    except LabError as e:
        if e.code != ErrorCode.UNREACHABLE or not autostart:
            raise
    lab = host.connect_or_start(simulate, None, origin(), kind)
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
        self._connect = connect
        self._lab: Optional[Lab] = None

    @property
    def lab(self) -> Lab:
        if self._lab is None:
            self._lab = self._connect(self.simulate, self.autostart, self.kind)
        return self._lab

    def running_lab(self) -> Lab:
        """The daemon only when it runs already: LabError UNREACHABLE otherwise."""
        if self._lab is None:
            self._lab = self._connect(self.simulate, False, self.kind)
        return self._lab

    def call(self, operation: Operation[R]) -> R:
        return self.lab.call(operation)

    def ask(self, question: str) -> bool:
        """yes or no in the terminal; --yes answers yes, no terminal answers no."""
        if self.yes:
            return True
        if not sys.stdin.isatty():
            print(f"{question} — not asked without a terminal: --yes", file=sys.stderr)
            return False
        answer = input(f"{question} [y/N] ").strip().lower()
        return answer in ("y", "yes")

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
