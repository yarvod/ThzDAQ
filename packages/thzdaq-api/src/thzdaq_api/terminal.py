"""A person at this terminal: whether one is there, and a line they type that
is given up when what it answers is answered elsewhere (in a window).

A script started by a person in their terminal asks there, as a window does,
what its start needs allowed; in an agent's shell nobody types, so only a
window answers.
"""

import sys
import threading
from typing import Optional

from thzdaq_api.origins import agent_shell

LOOK_S = 0.1  # how often an unanswered line looks whether it is still needed
ALLOW = "allow? [y/N] "  # asked of the person here about what waits for one
YES = ("y", "yes")


def yes(typed: str) -> bool:
    """A typed answer is yes; anything else (Enter too) is no."""
    return typed.strip().lower() in YES


def person_here() -> bool:
    """A person types into this terminal: one is attached, no agent drives it."""
    return sys.stdin.isatty() and not agent_shell()


def line(prompt: str, gone: threading.Event) -> Optional[str]:
    """The line typed after prompt; None once gone is set first."""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    typed = _windows_line(gone) if sys.platform == "win32" else _posix_line(gone)
    if typed is None:
        sys.stderr.write("\n")
    return typed


def _posix_line(gone: threading.Event) -> Optional[str]:
    import select

    while not gone.is_set():
        # A terminal is readable once a whole line is typed (Enter)
        if select.select([sys.stdin], [], [], LOOK_S)[0]:
            return sys.stdin.readline().strip()
    return None


def _windows_line(gone: threading.Event) -> Optional[str]:
    import msvcrt

    typed = []
    while not gone.is_set():
        if not msvcrt.kbhit():
            gone.wait(LOOK_S)
            continue
        char = msvcrt.getwche()
        if char in "\r\n":
            sys.stderr.write("\n")
            return "".join(typed).strip()
        if char == "\b":
            typed = typed[:-1]
        else:
            typed.append(char)
    return None
