"""thzdaq mcp, thzdaq agent-setup: the bench for agents (Claude Code, Codex)
that work in a folder next to the window.

thzdaq mcp serves MCP on stdin and stdout when the thzdaq-mcp package is
installed (the build has it): the package adds the command through an entry
point, so the command line never imports it. agent-setup writes into a folder
what the agents read there: the MCP server as this very command starts it
from any folder (.mcp.json for Claude Code, .codex/config.toml for Codex),
and the guide for agents (AGENTS.md, CLAUDE.md refers to it). Files a person
wrote stay: the MCP entry is added to theirs.
"""

import json
import shutil
import sys
import tomllib
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Dict, List

from thzdaq_api import guides, host

from thzdaq_cli.client import FAILED, OK, PROG, Client, Mistyped

PLUGINS = "thzdaq.cli"  # entry points of the packages that add a command
MCP = "mcp"
SERVER = "thzdaq"  # the MCP server's name in the agents' configs
INSTALL = "thzdaq mcp needs the thzdaq-mcp package: uv tool install 'thzdaq[mcp]'"

CLAUDE_CONFIG = ".mcp.json"
CODEX_CONFIG = Path(".codex") / "config.toml"
GUIDE = "AGENTS.md"
CLAUDE_GUIDE = "CLAUDE.md"
REFERENCE = f"@{GUIDE}"  # how CLAUDE.md takes another file in
# A call waits up to 50 s for a person and a wait up to 60 s: more than the
# 60 s Codex gives a tool by default
TOOL_TIMEOUT_S = 120

WRITTEN, ADDED, KEPT = "written", "added to", "kept"


def add(commands) -> None:
    serve = commands.add_parser(
        MCP, help="the MCP server for agents, on stdin and stdout"
    )
    serve.add_argument(
        "--workspace", help="its measurements go to data/ there (default: this folder)"
    )
    serve.set_defaults(run=serve_mcp)
    setup = commands.add_parser(
        "agent-setup", help="let Claude Code and Codex measure in a folder"
    )
    setup.add_argument("folder", nargs="?", default=".", help="default: this folder")
    setup.add_argument(
        "--force", action="store_true", help=f"replace {GUIDE} with this version's"
    )
    setup.set_defaults(run=agent_setup)


def serve_mcp(args, client: Client) -> int:
    found = entry_points(group=PLUGINS, name=MCP)
    if not found:
        print(f"{PROG}: {INSTALL}", file=sys.stderr)
        return FAILED
    (plugin,) = found
    return plugin.load()(simulate=args.simulate, workspace=args.workspace)


def command() -> List[str]:
    """This very command as another program starts it from any folder: the
    build's thzdaq-cli, the thzdaq of an environment (uv run, uv tool, pip),
    else this Python with the package."""
    if host.frozen():
        return [sys.executable]
    found = shutil.which(sys.argv[0])
    if found is not None and Path(found).stem == PROG:
        return [str(Path(found).absolute())]
    return [sys.executable, "-m", __package__]


def server_command(simulate: bool, folder: Path) -> List[str]:
    """thzdaq [--simulate] mcp --workspace FOLDER, absolute."""
    options = ["--simulate"] if simulate else []
    return [*command(), *options, MCP, "--workspace", str(folder)]


def claude_config(path: Path, started: List[str]) -> str:
    """The server among those the folder's .mcp.json has."""
    told = ADDED if path.exists() else WRITTEN
    try:
        config: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except json.JSONDecodeError as e:
        raise Mistyped(f"{path} is not JSON ({e}): fix it, then run again") from None
    servers = config.setdefault("mcpServers", {})
    servers[SERVER] = {"command": started[0], "args": started[1:]}
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return told


def codex_block(started: List[str]) -> str:
    """The server's table of config.toml (JSON strings are TOML strings)."""
    return (
        f"[mcp_servers.{SERVER}]\n"
        f"command = {json.dumps(started[0], ensure_ascii=False)}\n"
        f"args = {json.dumps(started[1:], ensure_ascii=False)}\n"
        f"tool_timeout_sec = {TOOL_TIMEOUT_S}\n"
    )


def codex_config(path: Path, started: List[str]) -> str:
    """Added to the folder's config when it has no server of that name."""
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        path.write_text(codex_block(started), encoding="utf-8")
        return WRITTEN
    text = path.read_text(encoding="utf-8")
    try:
        servers = tomllib.loads(text).get("mcp_servers", {})
    except tomllib.TOMLDecodeError as e:
        raise Mistyped(f"{path} is not TOML ({e}): fix it, then run again") from None
    if SERVER in servers:
        return KEPT
    path.write_text(f"{text.rstrip()}\n\n{codex_block(started)}", encoding="utf-8")
    return ADDED


def guide(path: Path, force: bool) -> str:
    if path.exists() and not force:
        return KEPT
    path.write_text(guides.guide(guides.AGENTS), encoding="utf-8")
    return WRITTEN


def claude_guide(path: Path) -> str:
    """CLAUDE.md takes AGENTS.md in."""
    if not path.exists():
        path.write_text(f"{REFERENCE}\n", encoding="utf-8")
        return WRITTEN
    text = path.read_text(encoding="utf-8")
    if REFERENCE in text:
        return KEPT
    path.write_text(f"{text.rstrip()}\n\n{REFERENCE}\n", encoding="utf-8")
    return ADDED


def agent_setup(args, client: Client) -> int:
    folder = Path(args.folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    started = server_command(args.simulate, folder)
    files = {
        CLAUDE_CONFIG: claude_config(folder / CLAUDE_CONFIG, started),
        str(CODEX_CONFIG): codex_config(folder / CODEX_CONFIG, started),
        GUIDE: guide(folder / GUIDE, args.force),
        CLAUDE_GUIDE: claude_guide(folder / CLAUDE_GUIDE),
    }
    told = {"folder": str(folder), "server": started, "files": files}
    client.out(told, setup_text)
    return OK


def setup_text(told: Dict[str, Any]) -> str:
    lines = [f"{state} {name}" for name, state in told["files"].items()]
    lines += [
        "",
        f"MCP server: {' '.join(told['server'])}",
        f"Claude Code reads {CLAUDE_CONFIG} when it starts in {told['folder']}; "
        f"Codex reads {CODEX_CONFIG} of a trusted project (or copy its table "
        "into ~/.codex/config.toml).",
        "What agents change waits for a person in the ThzDAQ window.",
    ]
    return "\n".join(lines)
