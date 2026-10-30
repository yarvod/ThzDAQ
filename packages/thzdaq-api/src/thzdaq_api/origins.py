"""Who calls the daemon: the origin each operation carries, the kind of a client
that listens. People do what they ask and answer for agents; agents and
scripts ask a person before they change the bench (thzdaq_core's Policy)."""

GUI = "gui"  # a window: people answer in it
CLI = "cli"  # the command line in a terminal of a person
AGENT_CLI = "cli:agent"  # the command line in a shell an agent runs
ASSISTANT = "assistant"  # the chat in the window
MCP = "mcp:"  # mcp:<the agent's name> (Claude Code, Codex)
SCRIPT = "script:"  # script:<its name>


def agent(origin: str) -> bool:
    """An agent or a script: what it changes waits for a person."""
    return origin in (AGENT_CLI, ASSISTANT) or origin.startswith((MCP, SCRIPT))
