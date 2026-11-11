"""Kept state: what only the program knows of an instrument.

A grid without position readback knows its angle by counting its moves; when
the program restarts, the count must not start from zero again. Such an
instrument tells every change of that state to whoever watches it (before a
move and after it) and takes it back when it opens again. Where the state is
kept (a file of the daemon) is not its business.

The state is a mapping of JSON values.
"""

from typing import Any, Callable, Dict, Mapping, Optional, Protocol, runtime_checkable

State = Dict[str, Any]
Told = Callable[[State], None]


@runtime_checkable
class KeptState(Protocol):
    def kept_state(self) -> State:
        """What it knows now, to be kept."""

    def restore_state(self, state: Mapping[str, Any]) -> None:
        """Take back what was kept, as it last told it."""

    def watch_state(self, told: Told) -> None:
        """told(state) hears every change, in the thread that makes it; a
        failure to keep it is the watcher's to handle, never raised here."""


class KeepsState:
    """The watching half of KeptState for an instrument class: it tells its
    state through keep()."""

    _told: Optional[Told] = None

    def kept_state(self) -> State:
        raise NotImplementedError

    def watch_state(self, told: Told) -> None:
        self._told = told

    def keep(self, state: Optional[State] = None) -> None:
        """Tell the state (its kept_state() unless given) to the watcher."""
        if self._told is not None:
            self._told(self.kept_state() if state is None else state)
