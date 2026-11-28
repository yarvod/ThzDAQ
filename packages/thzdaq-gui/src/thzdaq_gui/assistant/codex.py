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

The session is made as the chat is first shown (warm), so Codex's models,
their efforts and its modes are known before the first message; those last
known are kept in the settings and shown at once on the next start, until
the session tells its own. The person chooses a model, its effort and the
mode at any time: the mode goes at once, a turn running too (Codex then asks
for less, or more); full access is confirmed first.

A turn is one session/prompt. What the person sends while it runs waits and
goes as the next turn once it ended (taken then). Stop is session/cancel:
what Codex asked and nobody answered is answered cancelled. A session made in
another process, or with another workspace, server or instructions than the
window's now, is resumed with the window's at the next turn (session/resume).

Codex keeps its sessions itself: History lists those of the workspace
(session/list, told page by page: codex-acp pages through all of Codex's
sessions to find a folder's), one opens as Codex tells it again
(session/load, a Replay), and takes another title (session/set_title) when
the adapter offers that.

How much of Codex's usage limits is left (its 5-hour and weekly windows) is
read from Codex's own log of the session after each turn, and of its newest
logs as the chat is first shown (limits.py): codex-acp tells them over ACP
only in the words of /status.

Whatever waits (the process, its answers, the person's answer to what Codex
asks) waits in the agent's loop; the GUI thread only hands requests over and
reads, under a lock that is never held across a wait, what the loop told."""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, List, Optional, Protocol, Sequence, Tuple

from thzdaq_api import host
from thzdaq_api.errors import LabError

from thzdaq_gui.assistant.acp import (
    Agent,
    Command,
    Offer,
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
from thzdaq_gui.assistant import limits
from thzdaq_gui.assistant.builtin import Instructions
from thzdaq_gui.assistant.chat import (
    Chat,
    Choice,
    Found,
    Kept,
    Limit,
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
FULL_ACCESS = "agent-full-access"
# Codex's modes (codex-acp's AgentMode), for the settings before any session
MODES = (
    Choice("read-only", "Read-only", "Asks before it edits a file or uses the network"),
    Choice(
        WORKSPACE_WRITE, "Workspace access",
        "Edits the workspace; asks before it writes outside it or uses the network",
    ),
    Choice("agent", "Auto review", "Asks only for what looks unsafe"),
    Choice(FULL_ACCESS, "Full access", "Any file, the network: asks nothing"),
)  # fmt: skip
CONFIRM_FULL_ACCESS = (
    "In full access Codex runs any command, changes any file on this computer"
    " and uses the network without asking you first. Give it full access?"
)
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

    def known(self) -> Optional[Options]:
        """The options a session told last; None before any."""

    def keep(self, options: Options) -> None:
        """Remember the options a session told, from any thread."""


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
        self._policy: Optional[str] = None  # chosen for the next new session
        self._options = self._unmade()  # as shown: the session's once it told them
        self._limit: Optional[int] = None
        self._limits: Tuple[Limit, ...] = ()  # as Codex's log told them last
        self._titles = False
        self._finding = False  # warm() makes a session that tells its options
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

    def _unmade(self) -> Options:
        """The options shown before a session tells its own: those a session
        told last (Codex's modes, when it told none), in the mode a new chat
        takes."""
        known = self.settings.known() or Options()
        if not known.policies.choices:
            modes = tuple(replace(mode, id=choice(MODE, mode.id)) for mode in MODES)
            known = replace(known, policies=Offer(MODE, modes))
        return known.chose(self._policy or choice(MODE, self.settings.mode()))

    def start(self, said: Optional[Said], listener: Listener) -> None:
        setup = self._setup()
        given = [said] if said is not None else self._waiting
        taken = 0 if said is not None else len(self._waiting)
        self._waiting = []
        self._turn = turn = _Turn(listener)
        self.agent.soon(self._run(turn, tuple(given), taken, setup))

    def warm(self) -> None:
        try:
            setup = self._setup()
        except Unready as e:  # the turn tells why
            logger.warning("Codex was not started: %s", e)
            return
        with self._lock:
            self._finding = True
        self._changed()
        self.agent.soon(self._warm(setup))
        # The account's limits as Codex's newest logs tell them, meanwhile
        self.agent.soon(self._read_limits(setup.command, None))

    def finding(self) -> bool:
        with self._lock:
            return self._finding

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
        """The next session starts in the settings' mode."""
        self._waiting, self._turn = [], None
        with self._lock:
            self._kept, self._policy = None, None
            self._options = self._options.chose(choice(MODE, self.settings.mode()))
        self._changed()
        self.agent.soon(self._forget())

    def current(self) -> Optional[Kept]:
        with self._lock:
            return self._kept

    def chats(self, workspace: Path, found: Found) -> None:
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
            return self._options.models.choices

    def model(self) -> Optional[str]:
        with self._lock:
            return self._options.models.chosen

    def choose(self, model: str) -> None:
        """Remembered: a new session takes it too."""
        self.settings.choose(model)
        self._set(model)

    def efforts(self) -> Sequence[Choice]:
        with self._lock:
            return self._options.efforts.choices

    def effort(self) -> Optional[str]:
        with self._lock:
            return self._options.efforts.chosen

    def choose_effort(self, effort: str) -> None:
        self.choose(effort)

    def policies(self) -> Sequence[Choice]:
        """Codex's modes; full access asks first."""
        with self._lock:
            modes = self._options.policies.choices
        full = choice(MODE, FULL_ACCESS)
        return tuple(
            replace(mode, confirm=CONFIRM_FULL_ACCESS) if mode.id == full else mode
            for mode in modes
        )

    def policy(self) -> Optional[str]:
        with self._lock:
            return self._options.policies.chosen

    def choose_policy(self, policy: str) -> None:
        """Of this chat only: before its session, the one it is made with."""
        with self._lock:
            self._policy = policy
        self._set(policy)

    def _set(self, made: str) -> None:
        """Shown chosen at once; the session's option set in the loop."""
        with self._lock:
            self._options = self._options.chose(made)
        self._changed()
        self.agent.soon(self._choose(made))

    def context_limit(self) -> Optional[int]:
        with self._lock:
            return self._limit

    def limits(self) -> Sequence[Limit]:
        with self._lock:
            return self._limits

    def watch(self, changed: Callable[[], None]) -> None:
        self._changed = changed

    # What the session tells (acp.Heard), from the loop
    def sized(self, tokens: int) -> None:
        with self._lock:
            known, self._limit = self._limit, tokens
        if known != tokens:
            self._changed()

    def configured(self, options: Options) -> None:
        """Kept for the next start too, when it offers models."""
        with self._lock:
            self._options, self._finding = options, False
        if options.models.choices:
            self.settings.keep(options)
        self._changed()

    def titled(self, session: str, title: str) -> None:
        with self._lock:
            self._kept = renamed(self._kept, session, title=title)

    # In the loop
    async def _run(
        self, turn: _Turn, said: Tuple[Said, ...], taken: int, setup: Setup
    ) -> None:
        async with self._prompting:  # a turn stopped before ends first
            if turn.stopped:
                return
            listener = turn.listener
            try:
                session = await self._session(setup)
            except Problem as e:
                listener.ended(Outcome.FAILED, str(e))
                return
            with self._lock:
                if turn.stopped:  # the window went on to another chat
                    return
                if self._kept is None or self._kept.id != session:  # it begins
                    title = title_of(said[0])
                    self._kept = Kept(session, title, time.time(), setup.folder)
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
        await self._read_limits(setup.command, session)

    async def _warm(self, setup: Setup) -> None:
        """A session made before the first message, so its options are
        known; what fails is told by the first turn."""
        async with self._prompting:
            try:
                await self._session(setup)
            except Problem as e:
                logger.warning("Codex's session was not made: %s", e)
            with self._lock:
                self._finding = False
            self._changed()

    async def _read_limits(self, command: Command, session: Optional[str]) -> None:
        """The usage limits as Codex's log of the session (None: its newest
        logs) tells them last, read in a thread of its own; those shown stay
        while it tells none, or older ones."""
        found = await asyncio.to_thread(
            limits.latest, limits.home(dict(command.environment)), session
        )
        with self._lock:
            known = self._limits
            if not found or (known and found[0].told < known[0].told):
                return
            self._limits = found
        if known != found:
            self._changed()

    async def _session(self, setup: Setup) -> str:
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
            await self._defaults(made.session_id, made.config_options)
        elif self._made != (ready.process, setup):
            options = await self.agent.resume_session(
                self._id, setup.folder, servers, setup.instructions
            )
            self._made = (ready.process, setup)
            self.configured(options)
        return self._id

    def _wanted(self) -> Tuple[str, ...]:
        """What a new session is set to: the mode chosen for it (else the
        settings'), then what the person chose of the options last. Read as
        the session is made: a choice made while it was being made goes too."""
        with self._lock:
            policy = self._policy
        return (policy or choice(MODE, self.settings.mode()), *self.settings.chosen())

    async def _defaults(self, session: str, found: Optional[Sequence[Any]]) -> None:
        """A new session in the mode wanted, with the options the person
        chose last that it offers (a model's efforts after it)."""
        options = options_of(found)
        for made in self._wanted():
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

    async def _list(self, command: Command, folder: Path, found: Found) -> None:
        """Told page by page as the adapter finds them, then whole."""
        kept: List[Kept] = []

        def newest() -> List[Kept]:
            return sorted(kept, key=lambda chat: chat.updated, reverse=True)

        try:
            await self._reach(command)
            async for page in self.agent.sessions(folder):
                if page:
                    kept += page
                    found(newest(), False)
        except Problem as e:
            logger.warning("Codex's chats were not listed: %s", e)
        found(newest(), True)

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
