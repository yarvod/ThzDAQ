"""Codex as a chat of the assistant's dock (chat.Chat), over ACP: codex-acp,
Codex's adapter, a child process reached by acp.Agent. No Qt.

A chat is a session of the adapter, made at the first message in the
window's workspace with the bench's MCP server as agent-setup writes it (the
window's command line, mcp --workspace <folder>, --simulate while the window
works with the simulator) and the person's instructions as its systemPrompt:
codex-acp appends them to Codex's developer instructions (it takes no other
mode), Codex's own prompt stays. A new session starts in the mode of the
settings (workspace-write unless the person chose another) with the model and
reasoning effort the person chose last. Codex reaches the bench only through
that server, as the agent mcp:<its name>: what it changes waits for the
person in the window, as any agent's; what it runs or writes on its own it
asks first (session/request_permission, a card in the chat).

A turn is one session/prompt. What the person sends while it runs waits and
goes as the next turn once it ended (taken then). Stop is session/cancel:
what Codex asked and nobody answered is answered cancelled. A session made in
another process, or with another workspace, server or instructions than the
window's now, is resumed with the window's at the next turn (session/resume).

Codex keeps its sessions itself: History lists those of the workspace
(session/list), one opens as Codex tells it again (session/load, a Replay),
and takes another title (session/set_title) when the adapter offers that.

Whatever waits (the process, its answers, the person's answer to what Codex
asks) waits in the agent's loop; the GUI thread only hands requests over and
reads, under a lock that is never held across a wait, what the loop told."""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Protocol, Sequence, Tuple

from thzdaq_api import host
from thzdaq_api.errors import LabError

from thzdaq_gui.assistant.acp import (
    Agent,
    Command,
    Options,
    Problem,
    Ready,
    Retold,
    Told,
    Wanted,
    choice,
    options_of,
    probe,
    renamed,
    server,
    used_of,
)
from thzdaq_gui.assistant.builtin import Instructions
from thzdaq_gui.assistant.chat import (
    Chat,
    Choice,
    Kept,
    Listener,
    Outcome,
    Replay,
    Said,
    Unready,
)
from thzdaq_gui.assistant.history import title_of

logger = logging.getLogger(__name__)

TITLE = "Codex"
ADAPTER = "@agentclientprotocol/codex-acp"
COMMAND = f"npx -y {ADAPTER}"  # the adapter as npm gives it
EXECUTABLE = "CODEX_PATH"  # the codex the adapter runs; unset: its own
SETTINGS = "Settings → Codex (the gear above)"
WANTED = Wanted(
    ADAPTER, (2, 7, 0), (3, 0, 0), SETTINGS,
    "Codex is not signed in: run `codex login` in a terminal (with the codex"
    f" of {SETTINGS}), then send again.",
)  # fmt: skip
MODE = "mode"  # the session's option of Codex's approvals and sandbox
WORKSPACE_WRITE = "workspace-write"
# Codex's modes (codex-acp's AgentMode), for the settings before any session
MODES = (
    Choice("read-only", "Read-only", "Asks before it edits a file or uses the network"),
    Choice(
        WORKSPACE_WRITE, "Workspace access",
        "Edits the workspace; asks before it writes outside it or uses the network",
    ),
    Choice("agent", "Auto review", "Asks only for what looks unsafe"),
    Choice(
        "agent-full-access", "Full access",
        "Any file, the network: asks nothing",
    ),
)  # fmt: skip
# How a turn ended, by the stop reason of ACP
ENDINGS = {
    "end_turn": (Outcome.ANSWERED, ""),
    "cancelled": (Outcome.STOPPED, ""),
    "max_tokens": (
        Outcome.FAILED, "Codex stopped at its token limit: say “go on” to continue."
    ),
    "max_turn_requests": (
        Outcome.FAILED,
        "Codex stopped after the most requests of a turn: say “go on” to continue.",
    ),
    "refusal": (Outcome.FAILED, "Codex refused to answer."),
}  # fmt: skip


class Folder(Protocol):
    folder: Path


class Window(Protocol):
    """The window's session, as Codex needs it: its workspace (where Codex
    works and measures), and whether it works with the simulator (so does the
    bench's server it gives Codex)."""

    workspace: Folder
    simulate: bool


class Settings(Protocol):
    """Codex's settings (models/assistant.py, CodexSettingsModel)."""

    def command(self) -> str:
        """The adapter's command line."""

    def executable(self) -> str:
        """The codex it runs; empty: its own."""

    def mode(self) -> str:
        """The mode a new chat starts in."""

    def chosen(self) -> Sequence[str]:
        """What the person chose of a session's options last (choice ids)."""

    def choose(self, made: str) -> None:
        """Remember a choice (in place of the one of the same option)."""


def command(settings: Settings) -> Command:
    """The adapter's process as the settings have it: the program's
    environment, CODEX_PATH when a codex is chosen."""
    environment = dict(os.environ)
    if settings.executable():
        environment[EXECUTABLE] = settings.executable()
    return Command.of(settings.command(), environment)


def test(settings: Settings, tested: Callable[[bool, str], None]) -> None:
    """Start the adapter of the settings, initialize it, tell tested what was
    found or what is wrong, from a thread of its own. Never waits."""
    probe(WANTED, command(settings), tested)


@dataclass(frozen=True)
class Setup:
    """What a session is made with: the adapter, the workspace, the bench's
    server, the person's instructions."""

    command: Command
    folder: Path
    server: Tuple[str, ...]
    instructions: str


class _Turn:
    """A turn: its listener, the session it prompts once it does; stopped by
    the GUI thread (under the chat's lock)."""

    def __init__(self, listener: Listener):
        self.listener = listener
        self.session: Optional[str] = None
        self.stopped = False


class CodexChat(Chat):
    title = TITLE

    def __init__(self, session: Window, settings: Settings, instructions: Instructions):
        self.session = session
        self.settings = settings
        self.instructions = instructions
        self.agent = Agent(WANTED, "codex")
        self._changed: Callable[[], None] = lambda: None
        # In the GUI thread
        self._waiting: List[Said] = []  # sent while a turn runs: the next turn's
        self._turn: Optional[_Turn] = None  # the last one begun
        # Told by the loop, read by the GUI thread: the lock only guards these
        self._lock = threading.Lock()
        self._kept: Optional[Kept] = None
        self._options = Options()
        self._limit: Optional[int] = None
        self._titles = False
        # In the loop
        self._id: Optional[str] = None  # the session going on
        self._made: Optional[Tuple[int, Setup]] = None  # its process, its setup
        self._prompting = asyncio.Lock()  # a turn, an opening: one at a time

    # What the window asks, in the GUI thread
    def _setup(self) -> Setup:
        folder = self.session.workspace.folder
        try:
            cli = host.cli_command()
        except LabError as e:
            raise Unready(str(e)) from None
        return Setup(
            command(self.settings),
            folder,
            tuple(host.mcp_server(cli, self.session.simulate, folder)),
            self.instructions.instructions(),
        )

    def start(self, said: Optional[Said], listener: Listener) -> None:
        setup = self._setup()
        given = [said] if said is not None else self._waiting
        taken = 0 if said is not None else len(self._waiting)
        self._waiting = []
        defaults = (choice(MODE, self.settings.mode()), *self.settings.chosen())
        self._turn = turn = _Turn(listener)
        self.agent.soon(self._run(turn, tuple(given), taken, setup, defaults))

    def queue(self, said: Said) -> None:
        self._waiting.append(said)

    def stop(self) -> None:
        self._waiting = []
        turn = self._turn
        if turn is None:
            return
        with self._lock:
            turn.stopped = True
        self.agent.soon(self._stop(turn))

    def new_chat(self) -> None:
        self._waiting, self._turn = [], None
        with self._lock:
            self._kept = None
        self.agent.soon(self._forget())

    def current(self) -> Optional[Kept]:
        with self._lock:
            return self._kept

    def chats(self, workspace: Path, found: Callable[[Sequence[Kept]], None]) -> None:
        self.agent.soon(self._list(command(self.settings), workspace, found))

    def open(self, chat: Kept, replay: Replay) -> None:
        self._waiting, self._turn = [], None
        with self._lock:
            self._kept = chat
        try:
            setup = self._setup()
        except Unready as e:
            replay.opened(str(e))
            return
        self.agent.soon(self._load(chat, replay, setup))

    def rename(self, chat: Kept, title: str) -> None:
        with self._lock:
            self._kept = renamed(self._kept, chat.id, title=title)
        self.agent.soon(self._rename(chat.id, title))

    def renames(self) -> bool:
        with self._lock:
            return self._titles

    def close(self) -> None:
        self.agent.close()

    def lab_changed(self) -> None:
        """The next turn compares the server it would give with its session's
        (Setup) and resumes the session with the window's."""

    def prompt_changed(self) -> None:
        """As lab_changed: the instructions are compared at the next turn;
        Codex's prompt holds nothing of the bench's profile."""

    def models(self) -> Sequence[Choice]:
        with self._lock:
            return self._options.choices

    def model(self) -> Optional[str]:
        with self._lock:
            return self._options.chosen

    def choose(self, model: str) -> None:
        self.settings.choose(model)
        self.agent.soon(self._choose(model))

    def context_limit(self) -> Optional[int]:
        with self._lock:
            return self._limit

    def watch(self, changed: Callable[[], None]) -> None:
        self._changed = changed

    # What the session tells (acp.Heard), from the loop
    def sized(self, tokens: int) -> None:
        with self._lock:
            known, self._limit = self._limit, tokens
        if known != tokens:
            self._changed()

    def configured(self, options: Options) -> None:
        with self._lock:
            self._options = options
        self._changed()

    def titled(self, session: str, title: str) -> None:
        with self._lock:
            self._kept = renamed(self._kept, session, title=title)

    # In the loop
    async def _run(
        self,
        turn: _Turn,
        said: Tuple[Said, ...],
        taken: int,
        setup: Setup,
        defaults: Tuple[str, ...],
    ) -> None:
        async with self._prompting:  # a turn stopped before ends first
            if turn.stopped:
                return
            listener = turn.listener
            try:
                session = await self._session(turn, setup, defaults, said)
            except Problem as e:
                listener.ended(Outcome.FAILED, str(e))
                return
            if turn.stopped:
                return
            if taken:
                listener.taken(taken)
            listener.asking()
            turn.session = session
            try:
                answered = await self.agent.prompt(
                    session, said, Told(listener, self, session)
                )
            except Problem as e:
                listener.ended(Outcome.FAILED, str(e))
                return
            with self._lock:
                self._kept = renamed(self._kept, session, updated=time.time())
            used = used_of(answered)
            if used is not None:
                listener.usage(used)
            listener.ended(*ENDINGS[answered.stop_reason])

    async def _session(
        self,
        turn: _Turn,
        setup: Setup,
        defaults: Tuple[str, ...],
        said: Tuple[Said, ...],
    ) -> str:
        """The session going on, made with the window's setup: a new one (in
        the mode and with the options chosen), or the one going on, resumed
        when it was made otherwise."""
        ready = await self._reach(setup.command)
        servers = [server(setup.server)]
        if self._id is None:
            made = await self.agent.new_session(
                setup.folder, servers, setup.instructions
            )
            self._id, self._made = made.session_id, (ready.process, setup)
            kept = Kept(made.session_id, title_of(said[0]), time.time(), setup.folder)
            with self._lock:
                if not turn.stopped:  # else the window went on to another chat
                    self._kept = kept
            await self._defaults(made.session_id, defaults, made.config_options)
        elif self._made != (ready.process, setup):
            options = await self.agent.resume_session(
                self._id, setup.folder, servers, setup.instructions
            )
            self._made = (ready.process, setup)
            self.configured(options)
        return self._id

    async def _defaults(
        self, session: str, defaults: Tuple[str, ...], found: Optional[Sequence[Any]]
    ) -> None:
        """A new session in the mode of the settings, with the options the
        person chose last that it offers (a model's efforts after it)."""
        options = options_of(found)
        for made in defaults:
            if not options.offers(made):
                continue
            try:
                options = await self.agent.choose(session, made)
            except Problem as e:  # the chat goes on as Codex made it
                logger.warning("Codex's option %s was not set: %s", made, e)
        self.configured(options)

    async def _reach(self, command: Command) -> Ready:
        ready = await self.agent.reach(command)
        with self._lock:
            self._titles = ready.titles
        return ready

    async def _stop(self, turn: _Turn) -> None:
        if turn.session is not None:
            await self.agent.cancel(turn.session)

    async def _forget(self) -> None:
        async with self._prompting:  # after the turn or the opening going on
            self._id = self._made = None

    async def _list(
        self, command: Command, folder: Path, found: Callable[[Sequence[Kept]], None]
    ) -> None:
        try:
            await self._reach(command)
            kept = await self.agent.sessions(folder)
        except Problem as e:
            logger.warning("Codex's chats were not listed: %s", e)
            kept = []
        found(sorted(kept, key=lambda chat: chat.updated, reverse=True))

    async def _load(self, chat: Kept, replay: Replay, setup: Setup) -> None:
        async with self._prompting:
            told = Retold(replay, self, chat.id)
            try:
                ready = await self._reach(setup.command)
                loaded = await self.agent.load_session(
                    chat.id, setup.folder, [server(setup.server)],
                    setup.instructions, told,
                )  # fmt: skip
            except Problem as e:
                self._id = self._made = None
                told.done(str(e))
                return
            self._id, self._made = chat.id, (ready.process, setup)
            self.configured(options_of(loaded.config_options))
            told.done()

    async def _rename(self, session: str, title: str) -> None:
        try:
            await self.agent.set_title(session, title)
        except Problem as e:
            logger.warning("Codex's chat was not renamed: %s", e)

    async def _choose(self, made: str) -> None:
        if self._id is None:
            return  # remembered: a new session takes it
        try:
            self.configured(await self.agent.choose(self._id, made))
        except Problem as e:
            logger.warning("Codex's option was not set: %s", e)
