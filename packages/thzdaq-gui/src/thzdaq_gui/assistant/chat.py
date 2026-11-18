"""A chat of the assistant's dock apart from what answers it (Chat): the
built-in assistant (builtin.py: a model's server with the bench's tools), and
Codex over ACP (codex.py), each a mode of the same dock. No Qt.

A chat starts a turn with what the person said and runs it in a thread of
its own, telling the listener it was given (Listener) what the turn does: a
step asked, the person's queued messages taken, pieces of thought and of
text, tool calls with their progress and answers, the tokens, and how the
turn ended; an agent that acts on its own (Codex) also asks the person
before it runs a command or writes a file, and waits for the answer. What the
person says while a turn runs is queued: it joins at the turn's next step, or
(Codex) goes once the turn ended. stop() ends the turn at once; what its
thread still tells after that is the owner's to drop (the view model hears
only the turn it began last).

A chat also offers its models (Choice), the one chosen, the reasoning
efforts of that one (when it has some), what the agent may do without asking
(its policies: Codex's modes; none for the built-in assistant), and how many
tokens of context the chosen model takes when that is known; watch() hears
when these change. Shown for the first time, it may get ready in the
background (warm: Codex starts its adapter and a session, so its models are
known before the first message).

A chat keeps its conversations, each under an id, in the workspace it began
in (Kept): it lists them, opens one to go on with it, and renames one. An
opened one is told again the way its turns told it (Replay, a Listener with
the turns' beginnings and the person's messages), so it comes back into the
view model by the path a live turn takes. The built-in chat keeps them as
files of the program (history.py); Codex keeps its own sessions and replays
one as it loads.
"""

import difflib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple, Union

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
    """Tokens of one step, or of an agent's turn summed over the requests it
    made: read, all the input the model read (each request reads the whole
    conversation again), of which cached came from the server's cache (None:
    not told); written, all it wrote, of which reasoning it thought; context,
    how much of the model's context the conversation fills now (None: not
    told)."""

    read: int = 0
    written: int = 0
    reasoning: int = 0
    context: Optional[int] = None
    cached: Optional[int] = None


@dataclass(frozen=True)
class Choice:
    """What the person may choose for a chat (a model, its effort, a policy):
    its id, its name as shown, more about it in a line, and what to ask the
    person before it is chosen (empty: nothing)."""

    id: str
    title: str
    tip: str = ""
    confirm: str = ""


@dataclass(frozen=True)
class Option:
    """An answer the person may give to what an agent asks: its id, its name
    as the agent words it, and what it does (allow or reject, once or
    always)."""

    id: str
    name: str
    allows: bool
    always: bool = False


@dataclass(frozen=True)
class Run:
    """A command an agent would run, and the folder it runs in ("": not
    told)."""

    line: str
    folder: str = ""


HUNK = "@@"  # a hunk of a diff begins


@dataclass(frozen=True)
class Change:
    """A file an agent would change: its path and its hunks, each the text
    before (None: the file is new) and after; of an edit, the lines around
    it only."""

    path: str
    hunks: Tuple[Tuple[Optional[str], str], ...]

    def diff(self) -> List[str]:
        """Its lines as a unified diff shows them ("+added", "-removed",
        " kept"), hunks apart ("@@"; the lines of a hunk the agent sent count
        from its own text, not the file's, so none are told)."""
        found: List[str] = []
        for old, new in self.hunks:
            lines = difflib.unified_diff(
                (old or "").splitlines(), new.splitlines(), lineterm="", n=3
            )
            found += [HUNK if line.startswith(HUNK) else line for line in lines][2:]
        return found[1:]  # the first hunk's mark

    def counted(self) -> Tuple[int, int]:
        """The lines it adds and removes."""
        lines = self.diff()
        added = sum(1 for line in lines if line.startswith("+"))
        return added, sum(1 for line in lines if line.startswith("-"))


@dataclass(frozen=True)
class Note:
    """What the agent tells of it in words (a host it would reach, a
    permission it wants)."""

    text: str


@dataclass(frozen=True)
class Inputs:
    """What else the agent would be given: names and values as text."""

    values: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class Files:
    """The files it would touch."""

    paths: Tuple[str, ...]


Part = Union[Run, Change, Note, Inputs, Files]


@dataclass(frozen=True)
class Asked:
    """What an agent asks the person before it acts on its own (Codex runs a
    command, writes a file, calls a tool): what it would do in a line, what it
    would act on (the command and its folder, each file's changes, its
    input), and the answers it offers."""

    title: str
    parts: Tuple[Part, ...]
    options: Tuple[Option, ...]


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

    def permission(self, asked: Asked, answer: Callable[[Optional[str]], None]) -> None:
        """The agent asks the person before it acts (Codex, ACP
        session/request_permission) and waits: answer(the id of the option
        chosen) from any thread, once; answer(None) when the turn is stopped
        first. The built-in chat never asks: it changes the bench only, whose
        consent the daemon asks for in the window."""


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

    def renames(self) -> bool:
        """Whether a kept conversation takes another title (rename); an agent
        that keeps its own titles may offer none."""
        return True

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

    def efforts(self) -> Sequence[Choice]:
        """How hard the chosen model may think (its reasoning efforts), in
        order; none when it offers no choice."""
        return ()

    def effort(self) -> Optional[str]:
        """The id of the effort chosen; None without one."""
        return None

    def choose_effort(self, effort: str) -> None:
        """The chosen model thinks so hard from now on (one of efforts())."""

    def policies(self) -> Sequence[Choice]:
        """What the agent may do without asking the person first (Codex's
        modes), in order; none when it never acts on its own."""
        return ()

    def policy(self) -> Optional[str]:
        """The id of the policy in force; None without one."""
        return None

    def choose_policy(self, policy: str) -> None:
        """The agent acts so from now on, a turn running too (one of
        policies())."""

    def warm(self) -> None:
        """The chat is shown for the first time: what makes its models known
        starts in the background. Never waits."""

    def finding(self) -> bool:
        """Whether its models are being found (warm) and not known yet."""
        return False

    @abstractmethod
    def context_limit(self) -> Optional[int]:
        """The tokens the chosen model takes, when known."""

    @abstractmethod
    def watch(self, changed: Callable[[], None]) -> None:
        """changed() is called, from any thread, once the models, efforts or
        policies, the ones chosen, whether models are being found or the
        context limit changed."""
