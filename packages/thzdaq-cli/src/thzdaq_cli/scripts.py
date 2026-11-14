"""thzdaq script start|list|logs|stop, thzdaq run-script: scripts the daemon
runs apart from any terminal, so closing this one leaves them running; their
output goes to data/scripts/<id>.log of their workspace. A script runs with
--python, else with the Python its workspace names (thzdaq.toml), else with
this command's (a build's thzdaq-cli.exe run-script); what
it may do without asking a person is given with --allow (set:<device>,
call:<device>, run:<procedure>, raw:<instrument>; an agent's allows
nothing: a script has the rights of whoever started it). stop cancels its
measurements, and ends it when it has not ended a few seconds later."""

import argparse
import runpy
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from thzdaq_api import host, interpreters
from thzdaq_api.scripts import (
    Grant,
    ListScripts,
    ReadScriptLog,
    ScriptInfo,
    StartScript,
    StopScript,
)

from thzdaq_cli import show
from thzdaq_cli.client import HERE, OK, Client, Mistyped

FOLLOW_S = 0.5  # how often logs -f looks for more output, as tail -f does


def add(commands) -> None:
    group = commands.add_parser(
        "script", help="scripts the daemon runs apart from this terminal"
    )
    actions = group.add_subparsers(dest="action", metavar="ACTION", required=True)
    start = actions.add_parser(
        "start", help="run a Python script in the daemon: it outlives this terminal"
    )
    start.add_argument("file", help="then -- and the script's arguments")
    start.add_argument(
        "--python",
        help="an environment's folder or its interpreter (default: the "
        "workspace's, else this command's)",
    )
    start.add_argument(
        "--allow", action="append", default=[], metavar="KIND:TARGET",
        help="done without asking: set:<device>, call:<device>, run:<procedure>,"
        " raw:<instrument> (raw writes, which no limit checks); a person's only",
    )  # fmt: skip
    start.add_argument(
        "--share", action="append", default=[], metavar="DEVICE",
        help="its measurements share it while another one sweeps it",
    )  # fmt: skip
    start.add_argument(
        "--workspace", help=f"its working folder, its log in data/scripts ({HERE})"
    )
    start.set_defaults(run=start_script)
    actions.add_parser("list", help="scripts running and lately ended").set_defaults(
        run=list_scripts
    )
    logs = actions.add_parser("logs", help="what a script printed")
    logs.add_argument("id", type=int)
    logs.add_argument("-f", "--follow", action="store_true", help="until it ends")
    logs.set_defaults(run=script_logs)
    stop = actions.add_parser(
        "stop", help="cancel its measurements, then end it if it goes on"
    )
    stop.add_argument("id", type=int)
    stop.set_defaults(run=stop_script)
    run = commands.add_parser(
        host.RUN_SCRIPT, help="run a Python file with this program's Python"
    )
    ran = run.add_mutually_exclusive_group(required=True)
    ran.add_argument("file", nargs="?", help="then the script's arguments, as python")
    ran.add_argument(
        host.MODULE, dest="module", help="a module as a program (python -m), then --"
    )
    # Everything after the file is the script's, as python takes it: the daemon
    # starts a script as <its python> <file> <arguments>
    run.add_argument("arguments", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    run.set_defaults(run=run_script)


def interpreter(given: str, workspace: Optional[Path]) -> Tuple[str, ...]:
    """How the daemon runs a file: --python, else the Python of its
    workspace."""
    if given:
        return (str(interpreters.python_in(interpreters.located(given))),)
    return interpreters.scripts_python(workspace)


def grants(given: List[str]) -> Tuple[Grant, ...]:
    try:
        return tuple(Grant.parse(text) for text in given)
    except ValueError as e:
        raise Mistyped(str(e)) from None


def script_text(info: ScriptInfo) -> str:
    lines = [show.script(info), f"log {info.log}"]
    if info.allow:
        lines.append("may " + ", ".join(str(grant) for grant in info.allow))
    return "\n".join(lines)


def start_script(args, client: Client) -> int:
    started = client.call(
        StartScript(
            path=str(Path(args.file).resolve()),
            python=interpreter(args.python, client.workspace),
            arguments=tuple(args.passed),
            workspace=client.folder(),
            allow=grants(args.allow),
            share=tuple(args.share),
        )
    )
    client.out(started, script_text)
    return OK


def list_scripts(args, client: Client) -> int:
    found = client.call(ListScripts())
    client.out(
        found,
        lambda s: show.table(
            ("id", "script", "status", "pid", "started", "log"),
            [(i.id, i.name, i.status, i.pid or "", i.started, i.log) for i in s],
        )
        or "no script",
    )
    return OK


def script_logs(args, client: Client) -> int:
    since = 0
    while True:
        part = client.call(ReadScriptLog(id=args.id, since=since))
        sys.stdout.write(part.text)
        sys.stdout.flush()
        since = part.next
        if part.text:
            continue  # more may wait already
        if not (args.follow and part.running):
            return OK
        time.sleep(FOLLOW_S)


def stop_script(args, client: Client) -> int:
    client.out(client.call(StopScript(id=args.id)), script_text)
    return OK


def run_script(args, client: Client) -> int:
    """The file as Python runs it: __main__, its folder first on the path; a
    module as python -m runs it (the kernel of a window's console)."""
    if args.module:
        sys.argv = [args.module, *args.passed]
        runpy.run_module(args.module, run_name="__main__", alter_sys=True)
        return OK
    path = Path(args.file).resolve()
    sys.argv = [str(path), *args.arguments, *args.passed]
    sys.path.insert(0, str(path.parent))
    runpy.run_path(str(path), run_name="__main__")
    return OK
