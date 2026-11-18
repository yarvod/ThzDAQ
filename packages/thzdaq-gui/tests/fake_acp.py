"""A fake ACP agent on stdio for the tests of Codex's mode, built with the
agent side of the same SDK (agent-client-protocol): what codex-acp does, as
far as the window uses it, with no Codex, npm or network.

    python fake_acp.py <config.json>

The config (JSON) chooses what it is and does:
- name, version, protocol: what initialize answers (an incompatible one too);
- titles, prompts: whether it offers session/set_title and a systemPrompt;
- login: session/new refuses: the account is not signed in;
- gate: a file initialize waits for before it answers;
- log: a file each request and notification it gets is written to (a JSON
  line: method, params), as it came: the tests read what the window sent;
- sessions, history: what session/list answers and session/load tells again
  (by session id: [kind, ...] entries, as answer() tells them).

A prompt's first words choose what the turn does: "tool" (a tool call with
its updates), "permission" (asks, then says what was chosen; "permission
long": a long command with codex-acp's every answer, "permission edit": a file
change whose diff came with its tool call's start, "permission mcp": a call of
the bench's tool named by its id alone; in full access it asks nothing and
says so), "wait" (until the turn is cancelled), "many <n>" (n pieces of
text), "die" (the process ends at once, saying why on its error output), else
a thought, the words said back in pieces and the context filled.

What it asks is shaped as codex-acp 2.7.0 shapes it (permissions/,
tool-calls/reporters/): a command not started has itself as the title and
{command, cwd} as raw input; an approval of a call told before (a file change,
an MCP tool) names its id, kind and status only.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from acp import PROTOCOL_VERSION
from acp.agent.router import build_agent_router
from acp.connection import Connection
from acp.core import DEFAULT_STDIO_BUFFER_LIMIT_BYTES
from acp.exceptions import RequestError
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    ContentToolCallContent,
    FileEditToolCallContent,
    ListSessionsResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    RequestPermissionRequest,
    RequestPermissionResponse,
    ResumeSessionResponse,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SessionInfo,
    SessionInfoUpdate,
    SessionNotification,
    SetSessionConfigOptionResponse,
    TextContentBlock,
    ToolCallProgress,
    ToolCallLocation,
    ToolCallStart,
    ToolCallUpdate,
    Usage,
    UsageUpdate,
    UserMessageChunk,
)
from acp.stdio import stdio_streams
from acp.utils import notify_model, request_model

MODELS = [("gpt-a", "A"), ("gpt-b", "B")]
EFFORTS = {"gpt-a": ["low", "high"], "gpt-b": ["medium"]}
MODES = [  # codex-acp's AgentMode
    ("read-only", "Read-only", "Requires approval to edit files and access the internet."),
    ("workspace-write", "Workspace access", "Edit workspace files; ask before writing outside the workspace or accessing the network."),
    ("agent", "Auto review", "Only ask for actions detected as potentially unsafe"),
    ("agent-full-access", "Full access", "Unrestricted access to the internet and any file on your computer"),
]  # fmt: skip
FULL_ACCESS = "agent-full-access"
CONTEXT = (1200, 272000)  # tokens filled, tokens it takes
# A turn's tokens as codex-acp sums them (TokenCount): input read fresh,
# cached reads and writes apart, output with the reasoning in it
USAGE = Usage(
    total_tokens=1045, input_tokens=100, cached_read_tokens=900,
    cached_write_tokens=20, output_tokens=25, thought_tokens=5,
)  # fmt: skip
LONG = (
    "python -m thzdaq_api.kernel --connection-file /very/long/path/"
    + "deeply_nested_folder/" * 12
    + "kernel.json && echo done\n"
    + "for f in $(ls data/*.json); do jq '.records | length' \"$f\"; done"
)
ANSWERS = {  # codex-acp's permissions/options.ts, by the request
    "short": [
        ("yes", "Yes, proceed", "allow_once"),
        ("no", "No, and tell Codex what to do differently", "reject_once"),
    ],
    "long": [
        ("yes", "Yes, proceed", "allow_once"),
        ("session", "Yes, and don't ask again for this command in this session", "allow_always"),
        ("prefix", "Yes, and don't ask again for commands that start with `python -m thzdaq_api.kernel --connection-file`", "allow_always"),
        ("decline", "No, continue without running it", "reject_once"),
        ("no", "No, and tell Codex what to do differently", "reject_once"),
    ],
    "edit": [
        ("yes", "Yes, proceed", "allow_once"),
        ("session", "Yes, and don't ask again for these files", "allow_always"),
        ("no", "No, and tell Codex what to do differently", "reject_once"),
    ],
}  # fmt: skip
OLD = "".join(f"line {n}\n" for n in range(1, 41))
NEW = OLD.replace("line 7\n", "line seven\n").replace("line 30\n", "")


def text(words: str) -> TextContentBlock:
    return TextContentBlock(type="text", text=words)


class Fake:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        path = config.get("log")
        self.log = Path(path).open("a", encoding="utf-8") if path else None
        self.conn: Connection = None
        self.values: Dict[str, Dict[str, str]] = {}  # session -> option -> value
        self.cancelled: Dict[str, asyncio.Event] = {}
        self.made = 0

    def note(self, method: str, params: Any) -> None:
        """Into the log: what came (a request, a notification), or what the
        client answered (method "answered")."""
        if self.log is not None:
            self.log.write(json.dumps({"method": method, "params": params}) + "\n")
            self.log.flush()

    async def tell(self, session: str, update: Any) -> None:
        await notify_model(
            self.conn,
            "session/update",
            SessionNotification(session_id=session, update=update),
        )

    def options(self, session: str) -> List[Any]:
        values = self.values[session]
        model = values["model"]
        return [
            SessionConfigOptionSelect(
                id="mode", name="Mode", category="mode", type="select",
                current_value=values["mode"],
                options=[
                    SessionConfigSelectOption(value=v, name=n, description=d)
                    for v, n, d in MODES
                ],
            ),
            SessionConfigOptionSelect(
                id="model", name="Model", category="model", type="select",
                current_value=model,
                options=[
                    SessionConfigSelectOption(value=v, name=n, description=f"model {n}")
                    for v, n in MODELS
                ],
            ),
            SessionConfigOptionSelect(
                id="reasoning_effort", name="Reasoning effort",
                category="thought_level", type="select",
                current_value=values["reasoning_effort"],
                options=[
                    SessionConfigSelectOption(value=e, name=e.capitalize())
                    for e in EFFORTS[model]
                ],
            ),
        ]  # fmt: skip

    def known(self, session: str) -> None:
        if session not in self.values:
            self.values[session] = {
                "mode": "agent", "model": "gpt-a", "reasoning_effort": "low",
            }  # fmt: skip
            self.cancelled[session] = asyncio.Event()

    # The agent's methods, as the SDK's router calls them
    async def initialize(self, protocol_version, **_):
        gate = self.config.get("gate")
        while gate and not Path(gate).exists():
            await asyncio.sleep(0.01)
        sessions = {"list": {}, "resume": {}}
        if self.config.get("titles", True):
            sessions["title"] = {}
        if self.config.get("prompts", True):
            sessions["systemPrompt"] = {}
        return {
            "protocolVersion": self.config.get("protocol", PROTOCOL_VERSION),
            "agentInfo": {
                "name": self.config.get("name", "@agentclientprotocol/codex-acp"),
                "title": "Codex",
                "version": self.config.get("version", "2.7.0"),
            },
            "agentCapabilities": {
                "loadSession": True,
                "promptCapabilities": {"image": True},
                "sessionCapabilities": sessions,
            },
            "authMethods": [],
        }

    async def new_session(self, cwd, mcp_servers=None, **_):
        if self.config.get("login"):
            raise RequestError.auth_required()
        self.made += 1
        session = f"new-{self.made}"
        self.known(session)
        return NewSessionResponse(
            session_id=session, config_options=self.options(session)
        )

    async def list_sessions(self, cwd=None, cursor=None, **_):
        found = [s for s in self.config.get("sessions", []) if s["cwd"] == cwd]
        return ListSessionsResponse(sessions=[SessionInfo(**s) for s in found])

    async def load_session(self, cwd, session_id, mcp_servers=None, **_):
        self.known(session_id)
        for entry in self.config.get("history", {}).get(session_id, []):
            await self.answer(session_id, *entry)
        return LoadSessionResponse(config_options=self.options(session_id))

    async def resume_session(self, session_id, cwd, mcp_servers=None, **_):
        self.known(session_id)
        return ResumeSessionResponse(config_options=self.options(session_id))

    async def set_config_option(self, config_id, session_id, value, **_):
        values = self.values[session_id]
        values[config_id] = value
        if config_id == "model":
            values["reasoning_effort"] = EFFORTS[value][0]
        return SetSessionConfigOptionResponse(config_options=self.options(session_id))

    async def cancel(self, session_id, **_):
        self.cancelled[session_id].set()

    async def prompt(self, session_id, prompt, **_):
        self.known(session_id)
        self.cancelled[session_id].clear()
        words = prompt[0].text
        first = words.split()[0] if words.split() else ""
        if first == "wait":
            await self.answer(session_id, "agent", "Waiting")
            await self.cancelled[session_id].wait()
            return PromptResponse(stop_reason="cancelled")
        if first == "permission":
            if self.values[session_id]["mode"] == FULL_ACCESS:
                await self.answer(session_id, "agent", "ran it without asking")
                return PromptResponse(stop_reason="end_turn")
            how = words.split()[1] if len(words.split()) > 1 else "short"
            asked = await request_model(
                self.conn,
                "session/request_permission",
                RequestPermissionRequest(
                    session_id=session_id,
                    tool_call=await self.call_asked(session_id, how),
                    options=[
                        PermissionOption(option_id=id, name=name, kind=kind)
                        for id, name, kind in ANSWERS.get(how, ANSWERS["short"])
                    ],
                ),
                RequestPermissionResponse,
            )
            chosen = getattr(asked.outcome, "option_id", "cancelled")
            self.note("answered", chosen)
            await self.answer(session_id, "agent", f"chose {chosen}")
            reason = "cancelled" if chosen == "cancelled" else "end_turn"
            return PromptResponse(stop_reason=reason)
        if first == "tool":
            await self.answer(
                session_id,
                "tool",
                "t1",
                "Read sis_bias_1",
                {"ref": "sis_bias_1"},
                "0 V",
            )
            await self.answer(session_id, "agent", "It reads 0 V.")
            return PromptResponse(stop_reason="end_turn", usage=USAGE)
        if first == "die":
            print("boom: the fake adapter fell over", file=sys.stderr, flush=True)
            os._exit(3)
        if first == "many":
            for _ in range(int(words.split()[1])):
                await self.answer(session_id, "agent", "x")
            return PromptResponse(stop_reason="end_turn")
        await self.answer(session_id, "thought", "Thinking it over")
        for piece in (f"You said: ", words):
            await self.answer(session_id, "agent", piece)
        used, size = CONTEXT
        await self.tell(
            session_id, UsageUpdate(session_update="usage_update", used=used, size=size)
        )
        await self.tell(
            session_id,
            SessionInfoUpdate(
                session_update="session_info_update", title=f"On {words}"
            ),
        )
        return PromptResponse(stop_reason="end_turn", usage=USAGE)

    async def call_asked(self, session: str, how: str) -> ToolCallUpdate:
        """The tool call a permission is asked about, as codex-acp sends it:
        a command not started whole; a file change or an MCP tool's call
        started first (its diff, its arguments), then named by id."""
        if how == "edit":
            await self.tell(
                session,
                ToolCallStart(
                    session_update="tool_call", tool_call_id="e1",
                    title="Editing files", kind="edit", status="pending",
                    content=[
                        FileEditToolCallContent(
                            type="diff", path="/work/scripts/sweep.py",
                            old_text=OLD, new_text=NEW,
                        ),
                        FileEditToolCallContent(
                            type="diff", path="/work/scripts/new_notes.md",
                            old_text=None, new_text="# Notes\n\nBias at 2.8 mV\n",
                        ),
                    ],
                ),
            )  # fmt: skip
            return ToolCallUpdate(
                tool_call_id="e1", kind="edit", status="pending", title="Edit files",
                locations=[
                    ToolCallLocation(path="/work/scripts/sweep.py"),
                    ToolCallLocation(path="/work/scripts/new_notes.md"),
                ],
            )  # fmt: skip
        if how == "mcp":
            await self.tell(
                session,
                ToolCallStart(
                    session_update="tool_call", tool_call_id="m1",
                    title="thzdaq: set_quantity", kind="execute",
                    status="pending",
                    raw_input={"ref": "sis_bias_1", "key": "voltage_set", "value": "2 mV"},
                ),
            )  # fmt: skip
            return ToolCallUpdate(tool_call_id="m1", kind="execute", status="pending")
        line = LONG if how == "long" else "ls -la"
        return ToolCallUpdate(
            tool_call_id="p1", title=line, kind="execute", status="pending",
            raw_input={"command": line, "cwd": "/work"},
        )  # fmt: skip

    async def answer(self, session: str, kind: str, *given: Any) -> None:
        """One entry of a turn: user, agent or thought words, or a tool call
        (id, title, input, answer) with its updates."""
        if kind == "user":
            await self.tell(
                session,
                UserMessageChunk(
                    session_update="user_message_chunk", content=text(given[0])
                ),
            )
        elif kind == "agent":
            await self.tell(
                session,
                AgentMessageChunk(
                    session_update="agent_message_chunk", content=text(given[0])
                ),
            )
        elif kind == "thought":
            await self.tell(
                session,
                AgentThoughtChunk(
                    session_update="agent_thought_chunk", content=text(given[0])
                ),
            )
        else:
            id, title, raw, answered = given
            await self.tell(
                session,
                ToolCallStart(
                    session_update="tool_call", tool_call_id=id, title=title,
                    kind="read", status="pending", raw_input=raw,
                ),
            )  # fmt: skip
            await self.tell(
                session,
                ToolCallProgress(
                    session_update="tool_call_update", tool_call_id=id,
                    status="in_progress",
                ),
            )  # fmt: skip
            await self.tell(
                session,
                ToolCallProgress(
                    session_update="tool_call_update", tool_call_id=id,
                    status="completed",
                    content=[ContentToolCallContent(type="content", content=text(answered))],
                ),
            )  # fmt: skip

    def set_title(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"title": " ".join(params["title"].split())}


async def main(config: Dict[str, Any]) -> None:
    fake = Fake(config)
    router = build_agent_router(fake)

    async def handle(method: str, params: Any, notification: bool) -> Any:
        fake.note(method, params)
        if method == "session/set_title":  # unstable: not among the SDK's routes
            return fake.set_title(params)
        return await router(method, params, notification)

    reader, writer = await stdio_streams(limit=DEFAULT_STDIO_BUFFER_LIMIT_BYTES)
    fake.conn = Connection(handle, writer, reader, listening=False)
    await fake.conn.main_loop()


if __name__ == "__main__":
    asyncio.run(main(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))))
