"""An agent of the Agent Client Protocol (ACP) as the assistant's dock
reaches it: a child process (Codex's adapter, codex-acp) and the protocol
SDK's client of it (agent-client-protocol). The only module that imports the
SDK. No Qt.

Agent is the one owner of the process: a thread of its own runs an asyncio
loop with the SDK's connection, as a console's kernel does (kernel.py). The
process starts at the first request, again after it ended or once its
command changed, and initialize checks the protocol's version and the
agent's (Wanted) before anything else goes. Another thread hands work to the
loop (soon) and goes on at once; what answers it is told from the loop's
thread, never waited for.

What a session tells (session/update) goes to whoever hears that session
now (a Route): a turn's listener (Told, chat.Listener) or a conversation told
again as it loads (Retold, chat.Replay), in the chat's words: pieces of text
and thought, tool calls and their answers, how full the context is; and to
the chat (Heard): its options, its title, its context's size. What the agent
asks before it acts (session/request_permission) waits in the loop for the
person's answer; cancel() answers it cancelled.

The SDK (1.0.0, ACP schema 1.23) lacks what codex-acp takes as unstable
parts of ACP: systemPrompt on session/new, load and resume, session/set_title,
and the capabilities that offer them (sessionCapabilities.systemPrompt and
.title), which its models drop. So requests go over the SDK's Connection with
its client router: the params are the SDK's models serialised, with the
unstable fields added (_ask), and initialize's answer is read for those
capabilities before the SDK's model takes it.
"""

import asyncio
import base64
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import (
    IO,
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
)

from acp import PROTOCOL_VERSION, RequestError
from acp.client.router import build_client_router
from acp.connection import Connection
from acp.core import DEFAULT_STDIO_BUFFER_LIMIT_BYTES
from acp.meta import AGENT_METHODS
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    AllowedOutcome,
    CancelNotification,
    ClientCapabilities,
    ConfigOptionUpdate,
    ContentToolCallContent,
    DeniedOutcome,
    FileEditToolCallContent,
    ImageContentBlock,
    Implementation,
    InitializeRequest,
    InitializeResponse,
    ListSessionsRequest,
    ListSessionsResponse,
    LoadSessionRequest,
    LoadSessionResponse,
    McpServerStdio,
    NewSessionRequest,
    NewSessionResponse,
    PermissionOption,
    PromptRequest,
    PromptResponse,
    RequestPermissionResponse,
    ResumeSessionRequest,
    ResumeSessionResponse,
    SessionConfigOptionSelect,
    SessionConfigSelectGroup,
    SessionInfo,
    SessionInfoUpdate,
    SetSessionConfigOptionResponse,
    SetSessionConfigOptionSelectRequest,
    TerminalToolCallContent,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
    UsageUpdate,
    UserMessageChunk,
)
from acp.utils import serialize_params
from pydantic import BaseModel
from thzdaq_api import host

from thzdaq_gui.assistant.attachments import Attachment
from thzdaq_gui.assistant.attachments import Kind as Given
from thzdaq_gui.assistant.history import UNTITLED
from thzdaq_gui.assistant.chat import (
    Asked,
    Call,
    Choice,
    Kept,
    Listener,
    Option,
    Outcome,
    Replay,
    Said,
    Used,
)
from thzdaq_gui.version import __version__

logger = logging.getLogger(__name__)

CLIENT = "thzdaq"  # how this program names itself to an agent
LOGIN_REQUIRED = -32000  # an ACP error: the agent's account is not signed in
SET_TITLE = "session/set_title"  # unstable in ACP: not among the SDK's methods
SYSTEM_PROMPT = "systemPrompt"  # unstable: of session/new, load and resume
APPEND = "append"  # a system prompt adds to the agent's own instructions
TITLES = "title"  # the session capability of set_title
END_S = 3.0  # how long a process may take to end once asked, before it is ended
ERRORS_BYTES = 16 * 1024  # the end of what the process wrote, when it fails
CHOICE = "="  # a choice of a session's option: "<option>=<value>"
FINAL = ("completed", "failed")  # a tool call's status once it is over
MODEL, EFFORT = "model", "thought_level"  # categories of a session's options

NOT_STARTED = (
    "The adapter did not start ({command}: {error}). Set its command in {where}."
)
NO_COMMAND = "No command for the adapter. Set it in {where}."
ENDED = "The adapter ended ({code})."
PROTOCOL = (
    "The adapter speaks ACP version {found}; this program speaks version {needed}."
    " Set another adapter in {where}."
)
VERSION_FOUND = (
    "Found {found}; this program needs {name} {low} or newer, older than {high}."
    " Set its command in {where}."
)
UNNAMED = "an agent that does not tell its name and version"
REFUSED = "{agent}: {error}"
CANNOT = "The adapter cannot {what}."
GONE = "The adapter ended: send again to start it anew."
TESTED = "{agent}, ACP version {protocol}"


class Problem(Exception):
    """The agent cannot be reached or refused: why, in words for the person."""


@dataclass(frozen=True)
class Wanted:
    """The agent a chat works with: its name as it tells it (agentInfo), the
    versions that work (from low, up to but not with high), where a person
    sets its command, and what to do when its account is not signed in."""

    name: str
    low: Tuple[int, ...]
    high: Tuple[int, ...]
    where: str
    login: str


@dataclass(frozen=True)
class Command:
    """How the agent's process starts: its command line, and the whole
    environment of the process."""

    argv: Tuple[str, ...]
    environment: Tuple[Tuple[str, str], ...]

    @staticmethod
    def of(line: str, environment: Mapping[str, str]) -> "Command":
        """A command line as a person writes it (quotes for spaces; on
        Windows backslashes are a path's)."""
        windows = os.name == "nt"
        argv = [
            part[1:-1] if windows and part[:1] == part[-1:] == '"' else part
            for part in shlex.split(line, posix=not windows)
        ]
        return Command(tuple(argv), tuple(sorted(environment.items())))


@dataclass(frozen=True)
class Ready:
    """An agent started and initialized: who it is, its protocol, what it
    offers; process: which start of it (a session is of one process)."""

    agent: str
    protocol: int
    process: int
    loads: bool = False  # session/load
    lists: bool = False  # session/list
    resumes: bool = False  # session/resume
    prompts: bool = False  # a systemPrompt of the client's
    titles: bool = False  # session/set_title
    images: bool = False  # images in a prompt


@dataclass(frozen=True)
class Options:
    """A session's options (ACP config options) as the chat offers them: its
    models, the one chosen shown with each of its reasoning efforts, the
    others by name (a choice's id: choice(option, value)); values: each
    option's value now, and those it takes."""

    choices: Tuple[Choice, ...] = ()
    chosen: Optional[str] = None
    values: Dict[str, str] = field(default_factory=dict)
    offered: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    def offers(self, made: str) -> bool:
        """Whether choosing it changes the session: an option it has, to a
        value it takes and has not now."""
        option, value = setting(made)
        return value in self.offered.get(option, ()) and self.values[option] != value


def choice(option: str, value: str) -> str:
    """The id of choosing value for a session's option."""
    return f"{option}{CHOICE}{value}"


def setting(made: str) -> Tuple[str, str]:
    """The option and the value of a choice's id."""
    option, _, value = made.partition(CHOICE)
    return option, value


def version_of(text: str) -> Optional[Tuple[int, ...]]:
    """1.2.3 of "1.2.3", "1.2.3-preview.1"; None when it is no version."""
    found = re.match(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(part) for part in found.groups()) if found else None


def dotted(version: Tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def _offered(raw: Dict[str, Any], capability: str) -> bool:
    """Whether initialize's answer offers a session capability the SDK's
    models do not know."""
    agent = raw.get("agentCapabilities") or {}
    return (agent.get("sessionCapabilities") or {}).get(capability) is not None


def checked(raw: Dict[str, Any], wanted: Wanted, process: int) -> Ready:
    """What initialize answered, when it is the agent wanted at a version
    that works; Problem with what was found and what is needed, else."""
    answered = InitializeResponse.model_validate(raw)
    if answered.protocol_version != PROTOCOL_VERSION:
        raise Problem(
            PROTOCOL.format(
                found=answered.protocol_version, needed=PROTOCOL_VERSION,
                where=wanted.where,
            )
        )  # fmt: skip
    info = answered.agent_info
    found = version_of(info.version) if info is not None else None
    if (
        info is None
        or info.name != wanted.name
        or found is None
        or not wanted.low <= found < wanted.high
    ):
        raise Problem(
            VERSION_FOUND.format(
                found=f"{info.name} {info.version}" if info is not None else UNNAMED,
                name=wanted.name, low=dotted(wanted.low), high=dotted(wanted.high),
                where=wanted.where,
            )
        )  # fmt: skip
    capabilities = answered.agent_capabilities
    sessions = capabilities.session_capabilities
    return Ready(
        f"{info.title or info.name} ({info.name} {info.version})",
        answered.protocol_version,
        process,
        loads=bool(capabilities.load_session),
        lists=sessions.list is not None,
        resumes=sessions.resume is not None,
        prompts=_offered(raw, SYSTEM_PROMPT),
        titles=_offered(raw, TITLES),
        images=bool(capabilities.prompt_capabilities.image),
    )


def options_of(found: Optional[Sequence[Any]]) -> Options:
    """The options of a session as the chat offers them (Options)."""
    selects = [
        option
        for option in found or ()
        if isinstance(option, SessionConfigOptionSelect)
    ]
    values = {option.id: option.current_value for option in selects}
    offered = {
        option.id: tuple(value for value, _, _ in _values(option)) for option in selects
    }
    model = next((option for option in selects if option.category == MODEL), None)
    if model is None:
        return Options(values=values, offered=offered)
    effort = next((option for option in selects if option.category == EFFORT), None)
    choices = []
    for value, name, about in _values(model):
        if value == model.current_value and effort is not None:
            choices += [
                Choice(choice(effort.id, level), f"{name} · {level_name}", level_about)
                for level, level_name, level_about in _values(effort)
            ]
        else:
            choices.append(Choice(choice(model.id, value), name, about))
    chosen = (
        choice(effort.id, effort.current_value)
        if effort is not None
        else choice(model.id, model.current_value)
    )
    return Options(tuple(choices), chosen, values, offered)


def _values(option: SessionConfigOptionSelect) -> List[Tuple[str, str, str]]:
    """The values a select option takes, groups flattened: (value, name,
    description)."""
    found = []
    for entry in option.options:
        listed = (
            entry.options if isinstance(entry, SessionConfigSelectGroup) else [entry]
        )
        found += [(each.value, each.name, each.description or "") for each in listed]
    return found


def kept_of(info: SessionInfo) -> Kept:
    """A session the agent lists, as a chat keeps it."""
    try:
        updated = datetime.fromisoformat(info.updated_at or "").timestamp()
    except ValueError:  # none told, or not ISO 8601: as old as can be
        updated = 0.0
    return Kept(info.session_id, info.title or UNTITLED, updated, Path(info.cwd))


def blocks(said: Sequence[Said], images: bool) -> List[BaseModel]:
    """What the person said as a prompt's content: the words with what is
    attached told, and the images when the agent takes them."""
    found: List[BaseModel] = []
    for each in said:
        words = "\n\n".join([each.text, *(a.told() for a in each.attachments)])
        found.append(TextContentBlock(type="text", text=words.strip()))
        if images:
            found += [
                ImageContentBlock(
                    type="image",
                    data=base64.b64encode(given.data).decode("ascii"),
                    mime_type=given.mime,
                )
                for given in each.attachments
                if given.kind is Given.IMAGE
            ]
    return found


def said_of(pieces: Sequence[Any]) -> Said:
    """A person's message told again in pieces (user_message_chunk)."""
    words = "".join(
        piece.text for piece in pieces if isinstance(piece, TextContentBlock)
    )
    images = tuple(
        Attachment.image(base64.b64decode(piece.data), mime=piece.mime_type)
        for piece in pieces
        if isinstance(piece, ImageContentBlock)
    )
    return Said(words, images)


def _words(content: Any) -> str:
    return content.text if isinstance(content, TextContentBlock) else ""


def _shown(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _answer_of(update: ToolCallUpdate) -> str:
    """What a tool call answered: its content in words, else its raw output."""
    told = []
    for content in update.content or ():
        if isinstance(content, ContentToolCallContent):
            told.append(_words(content.content))
        elif isinstance(content, FileEditToolCallContent):
            told.append(f"{content.path}\n{content.new_text}")
        elif isinstance(content, TerminalToolCallContent):
            told.append(f"terminal {content.terminal_id}")
    text = "\n".join(part for part in told if part)
    if not text and update.raw_output is not None:
        text = _shown(update.raw_output)
    return text


def _call_of(update: ToolCallUpdate) -> Call:
    """A tool call as the chat shows it: its title (else its kind), and what
    it was given (its raw input)."""
    given = update.raw_input
    arguments = given if isinstance(given, dict) else {}
    if given is not None and not isinstance(given, dict):
        arguments = {"input": given}
    return Call(update.tool_call_id, update.title or update.kind or "tool", arguments)


def asked_of(call: ToolCallUpdate, options: Sequence[PermissionOption]) -> Asked:
    """What the agent asks, as the chat shows it."""
    given = call.raw_input
    if isinstance(given, dict):
        detail = "\n".join(f"{key}: {_shown(value)}" for key, value in given.items())
    else:
        detail = "" if given is None else _shown(given)
    return Asked(
        call.title or call.kind or "",
        detail,
        tuple(
            Option(
                option.option_id, option.name,
                allows=option.kind.startswith("allow"),
                always=option.kind.endswith("always"),
            )
            for option in options
        ),
    )  # fmt: skip


def used_of(answered: PromptResponse) -> Optional[Used]:
    """The tokens of a turn, when the agent told them."""
    usage = answered.usage
    if usage is None:
        return None
    return Used(usage.input_tokens, usage.output_tokens, usage.thought_tokens or 0)


class Heard(Protocol):
    """What a session tells apart from its turns (the chat): from the loop."""

    def sized(self, tokens: int) -> None:
        """How many tokens its context takes."""

    def configured(self, options: Options) -> None:
        """Its options changed."""

    def titled(self, session: str, title: str) -> None:
        """It has a title (of the agent's, or set)."""


class Route(Protocol):
    """Who hears a session now: what it tells, what its agent asks."""

    def update(self, update: Any) -> None:
        ...

    def permission(self, asked: Asked, answer: Callable[[Optional[str]], None]) -> None:
        ...


class Told:
    """What a session tells as a turn runs, told to the turn's listener in
    the chat's words (a Route)."""

    def __init__(self, listener: Listener, heard: Heard, session: str):
        self.listener, self.heard, self.session = listener, heard, session
        self.calls: Set[str] = set()  # tool calls told
        self.told: Dict[type, Callable[[Any], None]] = {
            AgentMessageChunk: self._text,
            AgentThoughtChunk: self._thought,
            ToolCallStart: self._call,
            ToolCallProgress: self._call,
            UsageUpdate: self._usage,
            ConfigOptionUpdate: self._options,
            SessionInfoUpdate: self._info,
        }

    def update(self, update: Any) -> None:
        """What is not shown (plans, notices, commands, modes) is passed by."""
        told = self.told.get(type(update))
        if told is not None:
            told(update)

    def permission(self, asked: Asked, answer: Callable[[Optional[str]], None]) -> None:
        self.listener.permission(asked, answer)

    def _text(self, update: AgentMessageChunk) -> None:
        words = _words(update.content)
        if words:
            self.listener.text(words)

    def _thought(self, update: AgentThoughtChunk) -> None:
        words = _words(update.content)
        if words:
            self.listener.thought(words)

    def _call(self, update: ToolCallUpdate) -> None:
        """A call starts (a call told only by its update starts too); its
        answer once it is over."""
        if update.tool_call_id not in self.calls:
            self.calls.add(update.tool_call_id)
            self.listener.called(_call_of(update))
        if update.status in FINAL:
            self.listener.answered(
                update.tool_call_id, _answer_of(update), update.status == "failed"
            )

    def _usage(self, update: UsageUpdate) -> None:
        self.heard.sized(update.size)
        self.listener.usage(Used(context=update.used))

    def _options(self, update: ConfigOptionUpdate) -> None:
        self.heard.configured(options_of(update.config_options))

    def _info(self, update: SessionInfoUpdate) -> None:
        if update.title:
            self.heard.titled(self.session, update.title)


class Retold(Told):
    """A session told again as it loads (session/load), told to a Replay:
    the person's message, whole once all its pieces came, begins a turn and
    ends the one before. done() ends the last one and tells it opened.
    Nothing is asked of a conversation told again."""

    def __init__(self, replay: Replay, heard: Heard, session: str):
        super().__init__(replay, heard, session)
        self.replay = replay
        self.pieces: List[Any] = []  # of the person's message coming
        self.turn = False  # a turn was begun and not ended

    def update(self, update: Any) -> None:
        if isinstance(update, UserMessageChunk):
            self.pieces.append(update.content)
            return
        self._began()
        super().update(update)

    def permission(self, asked: Asked, answer: Callable[[Optional[str]], None]) -> None:
        answer(None)

    def done(self, why: str = "") -> None:
        self._began()
        if self.turn:
            self.replay.ended(Outcome.ANSWERED, "")
        self.replay.opened(why)

    def _began(self) -> None:
        if not self.pieces:
            return
        if self.turn:
            self.replay.ended(Outcome.ANSWERED, "")
        self.replay.began(said_of(self.pieces))
        self.pieces, self.turn = [], True


class _Client:
    """The client side the SDK's router calls, in the loop: what a session
    tells and what its agent asks go to the agent's routes. Files and
    terminals are the agent's own (not offered in initialize)."""

    def __init__(self, agent: "Agent"):
        self.agent = agent

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        route = self.agent.routes.get(session_id)
        if route is not None:
            route.update(update)

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: List[PermissionOption],
        **_: Any,
    ) -> RequestPermissionResponse:
        chosen = await self.agent.asked(session_id, asked_of(tool_call, options))
        outcome = (
            DeniedOutcome(outcome="cancelled")
            if chosen is None
            else AllowedOutcome(outcome="selected", option_id=chosen)
        )
        return RequestPermissionResponse(outcome=outcome)


def _settle(waiting: "asyncio.Future[Optional[str]]", chosen: Optional[str]) -> None:
    if not waiting.done():
        waiting.set_result(chosen)


def _log_failure(done: Future) -> None:
    if not done.cancelled() and done.exception() is not None:
        logger.error("The ACP client failed", exc_info=done.exception())


def _tail(errors: Optional[IO[bytes]]) -> str:
    """The end of what the process wrote to its error output."""
    if errors is None:
        return ""
    size = errors.seek(0, 2)
    errors.seek(max(0, size - ERRORS_BYTES))
    return errors.read().decode("utf-8", "replace").strip()


class Agent:
    """An ACP agent: its process and the SDK's client of it, in a thread of
    its own with an asyncio loop (see the module). soon() and close() are
    called from any thread; the rest runs in the loop."""

    def __init__(self, wanted: Wanted, name: str = "acp"):
        self.wanted = wanted
        self.loop = asyncio.new_event_loop()
        # In the loop
        self.ready: Optional[Ready] = None
        self.routes: Dict[str, Route] = {}  # session -> who hears it now
        self._waiting: Dict[str, Set[asyncio.Future]] = {}  # session -> asked
        self._command: Optional[Command] = None
        self._connection: Optional[Connection] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._errors: Optional[IO[bytes]] = None
        self._starts = 0
        self._reaching = asyncio.Lock()  # one start at a time
        # A program that ends without close() does not wait for this thread;
        # the process ends once its input closes with the program
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        self.loop.run_forever()
        self.loop.close()

    def soon(self, coroutine: Coroutine) -> None:
        """Into the loop, from any thread, never waited for; a failure
        nobody expected goes to the log."""
        asyncio.run_coroutine_threadsafe(coroutine, self.loop).add_done_callback(
            _log_failure
        )

    def close(self) -> None:
        """The process ends, then the thread. Never waits."""
        self.soon(self._close())

    async def _close(self) -> None:
        try:
            await self._end()
        finally:
            self.loop.stop()

    # The process
    async def reach(self, command: Command) -> Ready:
        """The agent of this command, started and initialized: again after it
        ended, or for another command. Problem when it cannot be."""
        async with self._reaching:  # a turn and a listing may ask at once
            ended = self._process is not None and self._process.returncode is not None
            if self._connection is not None and (ended or command != self._command):
                await self._end()
            if self._connection is None:
                await self._start(command)
            return self.ready

    async def _start(self, command: Command) -> None:
        if not command.argv:
            raise Problem(NO_COMMAND.format(where=self.wanted.where))
        environment = dict(command.environment)
        program = shutil.which(command.argv[0], path=environment.get("PATH"))
        if program is None:
            raise Problem(
                NOT_STARTED.format(
                    command=command.argv[0], error="not found",
                    where=self.wanted.where,
                )
            )  # fmt: skip
        self._errors = tempfile.TemporaryFile()
        try:
            process = await asyncio.create_subprocess_exec(
                program, *command.argv[1:],
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=self._errors, env=environment,
                limit=DEFAULT_STDIO_BUFFER_LIMIT_BYTES, **host.windowless(),
            )  # fmt: skip
        except OSError as e:
            self._errors.close()
            self._errors = None
            raise Problem(
                NOT_STARTED.format(
                    command=command.argv[0], error=e.strerror or e,
                    where=self.wanted.where,
                )
            ) from None  # fmt: skip
        self._starts += 1
        self._process, self._command = process, command
        self._connection = Connection(
            build_client_router(_Client(self)), process.stdin, process.stdout
        )
        request = InitializeRequest(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(
                name=CLIENT, title="ThzDAQ", version=__version__
            ),
        )
        try:
            raw = await self._ask(AGENT_METHODS["initialize"], request)
            self.ready = checked(raw or {}, self.wanted, self._starts)
        except Problem:
            await self._end()
            raise

    async def _end(self) -> None:
        """The connection closed and the process ended: asked to (its input
        closed), else made to. What it asked is answered cancelled."""
        connection, process, errors = self._connection, self._process, self._errors
        self._connection = self._process = self._errors = None
        self.ready = None
        for session in list(self._waiting):
            self.cancelled(session)
        self.routes.clear()
        if connection is not None:
            await connection.close()
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), END_S)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if errors is not None:
            errors.close()

    async def _ended(self) -> Problem:
        """Why the connection was lost: how the process ended, with the end of
        what it wrote."""
        code = "it closed its output"
        if self._process is not None:
            try:
                code = (
                    f"exit code {await asyncio.wait_for(self._process.wait(), END_S)}"
                )
            except asyncio.TimeoutError:
                code = "it closed its output and runs on"
        told = _tail(self._errors)
        message = ENDED.format(code=code)
        return Problem(f"{message}\n\n{told}" if told else message)

    async def _ask(
        self, method: str, params: Optional[BaseModel], **unstable: Any
    ) -> Any:
        """A request: its params the SDK's model, with what the SDK lacks
        added (unstable, by their names in ACP). Problem when the agent
        refused or ended."""
        if self._connection is None:
            raise Problem(CANNOT.format(what=method))
        given = serialize_params(params) if params is not None else {}
        try:
            return await self._connection.send_request(method, {**given, **unstable})
        except RequestError as e:
            if e.code == LOGIN_REQUIRED:
                raise Problem(self.wanted.login) from None
            details = f" ({_shown(e.data)})" if e.data else ""
            agent = self.ready.agent if self.ready is not None else method
            raise Problem(REFUSED.format(agent=agent, error=f"{e}{details}")) from None
        except ConnectionError:
            problem = await self._ended()
            await self._end()
            raise problem from None

    # Sessions
    def _offers(self) -> Ready:
        """What the agent reached offers; Problem once it ended."""
        if self.ready is None:
            raise Problem(GONE)
        return self.ready

    def _prompt(self, instructions: str) -> Dict[str, Any]:
        """The person's instructions as a systemPrompt, when there are some
        and the agent takes them."""
        if not instructions.strip() or not self._offers().prompts:
            return {}
        text = {"type": "text", "text": instructions}
        return {SYSTEM_PROMPT: {"mode": APPEND, "content": [text]}}

    async def new_session(
        self, folder: Path, servers: Sequence[McpServerStdio], instructions: str
    ) -> NewSessionResponse:
        request = NewSessionRequest(cwd=str(folder), mcp_servers=list(servers))
        return NewSessionResponse.model_validate(
            await self._ask(
                AGENT_METHODS["session_new"], request, **self._prompt(instructions)
            )
        )

    async def load_session(
        self,
        session: str,
        folder: Path,
        servers: Sequence[McpServerStdio],
        instructions: str,
        route: Route,
    ) -> LoadSessionResponse:
        """Its turns are told again to route before it answers."""
        if not self._offers().loads:
            raise Problem(CANNOT.format(what="open a chat it keeps"))
        self.routes[session] = route
        request = LoadSessionRequest(
            session_id=session, cwd=str(folder), mcp_servers=list(servers)
        )
        return LoadSessionResponse.model_validate(
            await self._ask(
                AGENT_METHODS["session_load"], request, **self._prompt(instructions)
            )
            or {}
        )

    async def resume_session(
        self,
        session: str,
        folder: Path,
        servers: Sequence[McpServerStdio],
        instructions: str,
    ) -> Options:
        """A session made before (by another process, or with another server
        or instructions) taken up with these, without telling it again;
        loaded and told to nobody when the agent cannot resume. Its options."""
        if not self._offers().resumes:
            self.routes.pop(session, None)
            found = await self.load_session(
                session, folder, servers, instructions, None
            )
            self.routes.pop(session, None)
            return options_of(found.config_options)
        request = ResumeSessionRequest(
            session_id=session, cwd=str(folder), mcp_servers=list(servers)
        )
        answered = ResumeSessionResponse.model_validate(
            await self._ask(
                AGENT_METHODS["session_resume"], request, **self._prompt(instructions)
            )
        )
        return options_of(answered.config_options)

    async def sessions(self, folder: Path) -> List[Kept]:
        """The sessions the agent keeps for a folder, every page of them."""
        if not self._offers().lists:
            return []
        found: List[SessionInfo] = []
        cursor: Optional[str] = None
        while True:
            request = ListSessionsRequest(cwd=str(folder), cursor=cursor)
            page = ListSessionsResponse.model_validate(
                await self._ask(AGENT_METHODS["session_list"], request)
            )
            found += page.sessions
            cursor = page.next_cursor
            if not cursor:
                return [kept_of(info) for info in found]

    async def prompt(
        self, session: str, said: Sequence[Said], route: Route
    ) -> PromptResponse:
        """A turn: what it tells goes to route; its end."""
        self.routes[session] = route
        request = PromptRequest(
            session_id=session, prompt=blocks(said, self._offers().images)
        )
        return PromptResponse.model_validate(
            await self._ask(AGENT_METHODS["session_prompt"], request)
        )

    async def cancel(self, session: str) -> None:
        """The turn running ends: what it asked is answered cancelled."""
        self.cancelled(session)
        if self._connection is None:
            return
        try:
            await self._connection.send_notification(
                AGENT_METHODS["session_cancel"],
                serialize_params(CancelNotification(session_id=session)),
            )
        except ConnectionError:
            return  # the process ended: nothing runs to cancel

    async def choose(self, session: str, made: str) -> Options:
        """A session's option set (choice's id); its options then."""
        option, value = setting(made)
        request = SetSessionConfigOptionSelectRequest(
            session_id=session, config_id=option, value=value
        )
        answered = SetSessionConfigOptionResponse.model_validate(
            await self._ask(AGENT_METHODS["session_set_config_option"], request)
        )
        return options_of(answered.config_options)

    async def set_title(self, session: str, title: str) -> None:
        if not self._offers().titles:
            raise Problem(CANNOT.format(what="rename a chat"))
        await self._ask(SET_TITLE, None, sessionId=session, title=title)

    # What the agent asks, in the loop
    async def asked(self, session: str, asked: Asked) -> Optional[str]:
        """The person's answer to what the agent asks (the id of the option
        chosen), or None: nobody hears the session, or its turn was
        stopped."""
        route = self.routes.get(session)
        if route is None:
            return None
        waiting: asyncio.Future = self.loop.create_future()
        self._waiting.setdefault(session, set()).add(waiting)

        def answer(chosen: Optional[str]) -> None:  # from any thread, once
            if not self.loop.is_closed():
                self.loop.call_soon_threadsafe(_settle, waiting, chosen)

        route.permission(asked, answer)
        try:
            return await waiting
        finally:
            self._waiting.get(session, set()).discard(waiting)

    def cancelled(self, session: str) -> None:
        for waiting in self._waiting.pop(session, ()):
            _settle(waiting, None)


def probe(
    wanted: Wanted, command: Command, tested: Callable[[bool, str], None]
) -> None:
    """Start the agent in a thread of its own, run initialize only, and tell
    tested whether it works with what was found (or what is wrong); the
    process ends then. Never waits."""
    agent = Agent(wanted, "acp test")

    async def run() -> None:
        try:
            ready = await agent.reach(command)
        except Problem as e:
            tested(False, str(e))
        else:
            tested(True, TESTED.format(agent=ready.agent, protocol=ready.protocol))
        finally:
            await agent._close()

    agent.soon(run())


def server(command: Sequence[str]) -> McpServerStdio:
    """The bench's MCP server as an agent starts it."""
    return McpServerStdio(
        name=host.MCP_NAME, command=command[0], args=list(command[1:]), env=[]
    )


def renamed(kept: Optional[Kept], session: str, **changed: Any) -> Optional[Kept]:
    """A kept session changed, when it is that session."""
    return replace(kept, **changed) if kept is not None and kept.id == session else kept
