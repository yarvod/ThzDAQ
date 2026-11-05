"""Who calls the daemon: the origin each operation carries, the kind of a client
that listens. People do what they ask and answer for agents; agents and
scripts ask a person before they change the bench (thzdaq_core's Policy)."""

import os
from typing import Optional

GUI = "gui"  # a window: people answer in it
CLI = "cli"  # the command line in a terminal of a person
AGENT_CLI = "cli:agent"  # the command line in a shell an agent runs
ASSISTANT = "assistant"  # the chat in the window
MCP = "mcp:"  # mcp:<the agent's name> (Claude Code, Codex)
MCP_CLIENT = "mcp"  # the kind of client an MCP server listens as
SCRIPT = "script:"  # script:<its name>
NUMBERED = "@"  # script:<its name>@<number>: one the daemon runs
SCRIPT_CLIENT = "script"  # the kind of client a script listens as
PLOTS = "plots"  # a plots window: it only shows, nobody answers in it

# The kind of a CLI that asks a person in its terminal what waits (approvals watch)
ANSWERING_CLI = "cli:answers"
ANSWERING = (GUI, ANSWERING_CLI)  # the kinds of client a person answers in

# Set in the shells agents run commands in (Claude Code, Codex): a command or
# a script started there is the agent's, so no person answers in its terminal
AGENT_SHELLS = ("CLAUDECODE", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")


def agent(origin: str) -> bool:
    """An agent or a script: what it changes waits for a person."""
    return origin in (AGENT_CLI, ASSISTANT) or origin.startswith((MCP, SCRIPT))


def answers(kind: str, origin: str) -> bool:
    """A client a person answers in: a window, or a terminal that asks; never
    one an agent runs."""
    return kind in ANSWERING and not agent(origin)


def scripted(origin: str) -> bool:
    """A script, by its origin: what it may do differs from an agent's only
    for raw commands (thzdaq_api.rights.SCRIPTS)."""
    return origin.startswith(SCRIPT)


def script(name: str, number: Optional[int] = None) -> str:
    """The origin of a script: script:<its name>, and @<number> for one the
    daemon runs (thzdaq script start)."""
    return f"{SCRIPT}{name}" + ("" if number is None else f"{NUMBERED}{number}")


def script_number(origin: str) -> Optional[int]:
    """The number of a script the daemon runs, by its origin; None for others."""
    head, numbered, number = origin.rpartition(NUMBERED)
    if not head.startswith(SCRIPT) or not numbered or not number.isdigit():
        return None
    return int(number)


def agent_shell() -> bool:
    """This process runs in a shell an agent drives (Claude Code, Codex)."""
    return any(os.environ.get(name) for name in AGENT_SHELLS)
