"""A chat of the assistant's dock apart from what answers it (Chat): the
built-in assistant (builtin.py: a model's server with the bench's tools), and
later Codex over ACP, each a mode of the same dock. No Qt.

A chat starts a turn with what the person said and runs it in a thread of
its own, telling the listener it was given (Listener) what the turn does: a
step asked, the person's queued messages taken, pieces of thought and of
text, tool calls with their progress and answers, the tokens, and how the
turn ended. What the person says while a turn runs is queued and joins at
its next step. stop() ends the turn at once; what its thread still tells
after that is the owner's to drop (the view model hears only the turn it
began last).

A chat also offers its models (Choice), the one chosen, and how many tokens
of context the chosen one takes when that is known; watch() hears when
these change.

A chat keeps its conversations, each under an id, in the workspace it began
in (Kept): it lists them, opens one to go on with it, and renames one. An
opened one is told again the way its turns told it (Replay, a Listener with
the turns' beginnings and the person's messages), so it comes back into the
view model by the path a live turn takes. The built-in chat keeps them as
files of the program (history.py); Codex keeps its own sessions and replays
one as it loads.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol, Sequence, Tuple

from thzdaq_gui.assistant.attachments import Attachment


class Outcome(str, Enum):
    ANSWERED = "answered"  # the model answered in words
    STOPPED = "stopped"  # the person stopped it
    STEPS = "steps"  # it took all its steps without an answer
    FAILED = "failed"  # the model's server or the daemon failed


@dataclass(frozen=True)
class Said:
    """What the person said: words and what is attached."""

    text: str
    attachments: Tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class Call:
    """A tool call as the chat shows it: its id within the turn, the tool,
    and its arguments ({} when the model wrote none that read)."""

    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Used:
    """Tokens of one step: what the model read, what it wrote and, of that,
    what it thought; context: how much of the model's context the
    conversation fills now (None: not told)."""

    read: int = 0
    written: int = 0
    reasoning: int = 0
    context: Optional[int] = None


@dataclass(frozen=True)
class Choice:
    """A model the person may choose for a chat: its id, its name as shown,
    and more about it (a tooltip)."""

    id: str
    title: str
    tip: str = ""


@dataclass(frozen=True)
class Kept:
    """A conversation a chat keeps: its id, its title, when a turn of it
    ended last (seconds since the epoch), and the workspace it is kept for."""

    id: str
    title: str
    updated: float
    workspace: Path


class Listener(Protocol):
    """What a turn tells as it goes, from the chat's thread."""

    def asking(self) -> None:
        """The model is asked: a step begins."""

    def taken(self, count: int) -> None:
        """The first count messages that waited joined the conversation."""

    def thought(self, piece: str) -> None:
        """A piece of what the model thinks before it answers."""

    def text(self, piece: str) -> None:
        """A piece of the model's answer."""

    def called(self, call: Call) -> None:
        """A tool call starts."""

    def progress(self, call: str, done: float, total: Optional[float]) -> None:
        """How far a call is (a measurement waited for)."""

    def answered(self, call: str, text: str, failed: bool) -> None:
        """What a call answered; failed: refused or wrong."""

    def usage(self, used: Used) -> None:
        """The tokens a step took."""

    def ended(self, outcome: Outcome, why: str) -> None:
        """The turn is over; why: what failed (FAILED)."""

    # Codex asks the person before it runs a command or writes a file
    # (ACP session/request_permission): permission(asked) with the options it
    # sends, answered with the one the person picks. Not told yet: the
    # built-in chat changes the bench only, whose consent the daemon asks.


class Replay(Listener, Protocol):
    """What a kept conversation tells as it is opened (Chat.open), from the
    chat's thread: each turn as it went, begun with what the person said,
    then what it told as a live turn tells it (pieces whole, no progress),
    with the person's messages that came while it ran, and its end. Last,
    opened(). How long a thought or a turn took is told when it was kept."""

    def began(self, said: Optional[Said]) -> None:
        """A turn begins, with what the person said (None: with what waited)."""

    def said(self, said: Said) -> None:
        """The person said this while the turn ran: it waited for its next
        step (taken) or was dropped by its end."""

    def thought(self, piece: str, seconds: Optional[float] = None) -> None:
        """What the model thought; seconds: how long, when it was kept."""

    def ended(
        self, outcome: Outcome, why: str, seconds: Optional[float] = None
    ) -> None:
        """The turn is over; seconds: how long it took, when it was kept."""

    def opened(self, why: str = "") -> None:
        """All of it was told; why: what of it could not be read."""


class Unready(Exception):
    """A chat cannot start a turn now (no model's server yet): why, in words
    for the person."""


class Chat(ABC):
    """A chat backend: its own conversation, its models, its turns."""

    title: str  # its mode's name in the dock

    @abstractmethod
    def start(self, said: Optional[Said], listener: Listener) -> None:
        """A turn answers said (None: only what is queued) in a thread of
        its own, telling listener, the last of it ended(). Unready when it
        cannot start one."""

    @abstractmethod
    def queue(self, said: Said) -> None:
        """What the person said while a turn runs: it joins at the turn's
        next step."""

    @abstractmethod
    def stop(self) -> None:
        """End the turn running at once; what is queued is dropped (so too
        once a turn ended)."""

    @abstractmethod
    def new_chat(self) -> None:
        """Forget the conversation (its turn was stopped first); the next
        message begins another one, kept under an id of its own."""

    @abstractmethod
    def current(self) -> Optional[Kept]:
        """The conversation going on, as kept; None before its first message."""

    @abstractmethod
    def chats(self, workspace: Path, found: Callable[[Sequence[Kept]], None]) -> None:
        """The conversations kept for a workspace, the newest first, told to
        found from a thread of the chat. Never waits."""

    @abstractmethod
    def open(self, chat: Kept, replay: Replay) -> None:
        """Go on with a kept conversation (its turn running was stopped
        first): it is told again to replay from a thread of the chat, and
        the next turn makes its prompt anew. Never waits."""

    @abstractmethod
    def rename(self, chat: Kept, title: str) -> None:
        """Give a kept conversation another title. Never waits."""

    @abstractmethod
    def close(self) -> None:
        """The window closes: let go of what the chat holds."""

    @abstractmethod
    def lab_changed(self) -> None:
        """The window works with another lab: the next turn reaches it anew,
        and makes its prompt anew. Never waits."""

    @abstractmethod
    def prompt_changed(self) -> None:
        """The bench's profile or the person's instructions changed: the
        next turn makes its prompt anew (a turn running keeps its own)."""

    @abstractmethod
    def models(self) -> Sequence[Choice]:
        """The models the person may choose, in order."""

    @abstractmethod
    def model(self) -> Optional[str]:
        """The id of the model chosen; None without one."""

    @abstractmethod
    def choose(self, model: str) -> None:
        """Turns from now on go to this model."""

    @abstractmethod
    def context_limit(self) -> Optional[int]:
        """The tokens the chosen model takes, when known."""

    @abstractmethod
    def watch(self, changed: Callable[[], None]) -> None:
        """changed() is called, from any thread, once the models, the one
        chosen or its context limit changed."""
