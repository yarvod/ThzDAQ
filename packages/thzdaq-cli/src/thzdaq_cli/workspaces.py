"""thzdaq init, thzdaq gui: workspaces, the folders of experiments.

init makes a folder a workspace: thzdaq.toml naming the profile it expects
(the daemon's by default), data/ and scripts/; with --agents also the files
Claude Code and Codex read (as agent-setup writes them). gui opens the window
in the workspace here, apart from this terminal: another window when one is
open already. The window is another program, started as installed (the
build's ThzDAQ, or the GUI package), never imported.
"""

from pathlib import Path
from typing import Any, Dict

from thzdaq_api import host, windows
from thzdaq_api.workspace import FILE, create, read

from thzdaq_cli import agents
from thzdaq_cli.client import OK, THIS_FOLDER, Client


def add(commands) -> None:
    init = commands.add_parser(
        "init", help="make a folder a workspace: thzdaq.toml, data/, scripts/"
    )
    init.add_argument("folder", nargs="?", default=".", help=THIS_FOLDER)
    init.add_argument(
        "--station",
        help="the profile it expects, by its name in stations/ (default: the "
        "daemon's, when one runs)",
    )
    init.add_argument(
        "--agents",
        action="store_true",
        help="also the files Claude Code and Codex read (as agent-setup)",
    )
    init.set_defaults(run=init_workspace)
    window = commands.add_parser("gui", help="open the window in the workspace here")
    window.add_argument(
        windows.WORKSPACE,
        help="the folder it opens (default: the workspace here or above, else "
        "the window's default)",
    )
    window.set_defaults(run=open_window)


def init_workspace(args, client: Client) -> int:
    folder = Path(args.folder).resolve()
    station = client.daemons_profile() if args.station is None else args.station
    written = create(folder, station)
    told: Dict[str, Any] = {
        "folder": str(folder),
        "files": {FILE: agents.WRITTEN if written else agents.KEPT},
        "station": read(folder).station,
    }
    if args.agents:
        told["agents"] = agents.setup(folder, args.simulate, agents.library(client))
    client.out(told, init_text)
    return OK


def init_text(told: Dict[str, Any]) -> str:
    expects = told["station"]
    lines = [
        f"{told['files'][FILE]} {FILE}: "
        + (f"expects the profile {expects!r}" if expects else "expects no profile"),
        f"workspace {told['folder']}: measurements go to its data/",
    ]
    if "agents" in told:
        lines += ["", agents.setup_text(told["agents"])]
    return "\n".join(lines)


def open_window(args, client: Client) -> int:
    command = windows.gui_command(client.workspace, client.simulate)
    host.start_apart(command)
    folder = str(client.workspace) if client.workspace else None
    client.out(
        {"workspace": folder, "command": command},
        lambda told: f"ThzDAQ opens in {told['workspace'] or 'its default workspace'}",
    )
    return OK
