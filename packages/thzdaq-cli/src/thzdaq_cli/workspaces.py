"""thzdaq init, thzdaq python, thzdaq gui: workspaces, the folders of
experiments.

init makes a folder a workspace: thzdaq.toml naming the profile it expects
(the daemon's by default) and, with --python, the Python its scripts run
with; data/ and scripts/; with --agents also the files Claude Code and Codex
read (as agent-setup writes them). python shows the Python of the workspace
here (checked: it has thzdaq of this program's version), sets another, or
lists the environments found (thzdaq_api.interpreters). gui opens the window
in the workspace here, apart from this terminal: another window when one is
open already. The window is another program, started as installed (the
build's ThzDAQ, or the GUI package), never imported.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from thzdaq_api import host, interpreters, windows
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.interpreters import Checked, Environment, check, check_own, stored
from thzdaq_api.workspace import FILE, create, is_workspace, read, write_python

from thzdaq_cli import agents, show
from thzdaq_cli.client import FAILED, HERE, OK, THIS_FOLDER, Client, Mistyped

OWN = "the program's own"  # the Python of a workspace that names none


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
        "--python",
        help="the Python its scripts run with: an environment's folder or its "
        "interpreter (default: the program's own)",
    )
    init.add_argument(
        "--agents",
        action="store_true",
        help="also the files Claude Code and Codex read (as agent-setup)",
    )
    init.set_defaults(run=init_workspace)
    python = commands.add_parser(
        "python", help="the Python the scripts of the workspace here run with"
    )
    actions = python.add_subparsers(dest="action", required=True, metavar="ACTION")
    shown = actions.add_parser("show", help="which one, checked")
    shown.set_defaults(run=show_python)
    chosen = actions.add_parser("set", help="choose another, then check it")
    chosen.add_argument(
        "path", nargs="?", help="an environment's folder (.venv) or its interpreter"
    )
    chosen.add_argument("--own", action="store_true", help="the program's own again")
    chosen.set_defaults(run=set_python)
    listed = actions.add_parser("list", help="environments found here, * the chosen")
    listed.set_defaults(run=list_pythons)
    for action in (shown, chosen, listed):
        action.add_argument("--workspace", help=HERE)
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
    python = given_python(folder, args.python) if args.python else ""
    written = create(folder, station, python)
    told: Dict[str, Any] = {
        "folder": str(folder),
        "files": {FILE: agents.WRITTEN if written else agents.KEPT},
        "station": read(folder).station,
        "python": python_told(folder),
    }
    if args.agents:
        told["agents"] = agents.setup(folder, args.simulate, agents.library(client))
    client.out(told, init_text)
    return OK if told["python"]["checked"].ok else FAILED


def init_text(told: Dict[str, Any]) -> str:
    expects = told["station"]
    lines = [
        f"{told['files'][FILE]} {FILE}: "
        + (f"expects the profile {expects!r}" if expects else "expects no profile"),
        f"workspace {told['folder']}: measurements go to its data/",
        python_text(told["python"]),
    ]
    if "agents" in told:
        lines += ["", agents.setup_text(told["agents"])]
    return "\n".join(lines)


def given_python(folder: Path, path: str) -> str:
    """How thzdaq.toml names a Python typed here; LabError when there is
    none there."""
    interpreters.python_in(interpreters.located(path))
    return stored(folder, path)


def python_told(folder: Optional[Path]) -> Dict[str, Any]:
    """The Python of a workspace: as its thzdaq.toml names it, the
    interpreter, checked."""
    named = read(folder).python if folder is not None else ""
    found = interpreters.chosen(folder)
    checked = check(found) if found is not None else check_own()
    return {"named": named, "python": str(found or ""), "checked": checked}


def python_text(told: Dict[str, Any]) -> str:
    checked: Checked = told["checked"]
    which = f"{told['named']} ({told['python']})" if told["named"] else OWN
    return f"scripts run with {which}: {checked.text()}"


def workspace_of(client: Client) -> Path:
    """The workspace of a command that writes its thzdaq.toml."""
    if client.workspace is None or not is_workspace(client.workspace):
        raise LabError(
            ErrorCode.NOT_FOUND,
            "No workspace here: the program's own folder runs scripts with "
            "the program's own Python",
            "thzdaq init makes a workspace",
        )
    return client.workspace


def show_python(args, client: Client) -> int:
    told = python_told(client.workspace)
    client.out(told, python_text)
    return OK if told["checked"].ok else FAILED


def set_python(args, client: Client) -> int:
    if bool(args.path) == args.own:
        raise Mistyped("set a path, or --own")
    folder = workspace_of(client)
    write_python(folder, given_python(folder, args.path) if args.path else "")
    return show_python(args, client)


def list_pythons(args, client: Client) -> int:
    found = interpreters.environments(client.workspace)
    now = interpreters.current(found, client.workspace)
    client.out(found, lambda listed: environments_text(listed, now))
    return OK


def environments_text(
    found: Tuple[Environment, ...], now: Optional[Environment]
) -> str:
    return show.table(
        ("", "kind", "name", "folder"),
        [("*" if e == now else "", e.kind, e.name, e.path) for e in found],
    )


def open_window(args, client: Client) -> int:
    command = windows.gui_command(client.workspace, client.simulate)
    host.start_apart(command)
    folder = str(client.workspace) if client.workspace else None
    client.out(
        {"workspace": folder, "command": command},
        lambda told: f"ThzDAQ opens in {told['workspace'] or 'its default workspace'}",
    )
    return OK
