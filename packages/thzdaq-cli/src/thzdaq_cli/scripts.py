"""thzdaq script start|list|logs|stop, thzdaq run-script: scripts the daemon
runs apart from any terminal, so closing this one leaves them running; their
output goes to data/scripts/<id>.log of their workspace. A script runs with
this command's Python (a build's thzdaq-cli.exe run-script) or --python; what
it may do without asking a person is given with --allow (set:<device>,
call:<device>, run:<procedure>). stop cancels its measurements, and ends it
when it has not ended a few seconds later."""

import runpy
import sys
import time
from pathlib import Path
from typing import List, Tuple

from thzdaq_api import host
from thzdaq_api.scripts import (
    RUNNING,
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
RUN_SCRIPT = "run-script"


def add(commands) -> None:
    group = commands.add_parser(
        "script", help="scripts the daemon runs apart from this terminal"
    )
    actions = group.add_subparsers(dest="action", metavar="ACTION", required=True)
    start = actions.add_parser(
        "start", help="run a Python script in the daemon: it outlives this terminal"
    )
    start.add_argument("file", help="then -- and the script's arguments")
    start.add_argument("--python", help="the interpreter (default: this command's)")
    start.add_argument(
        "--allow", action="append", default=[], metavar="KIND:TARGET",
        help="done without asking: set:<device>, call:<device>, run:<procedure>",
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
        RUN_SCRIPT, help="run a Python file with this program's Python"
    )
    run.add_argument("file", help="then -- and the script's arguments")
    run.set_defaults(run=run_script)


def interpreter(given: str) -> Tuple[str, ...]:
    """How the daemon runs a file: --python, else this command's Python; a
    build has none but its own (thzdaq-cli.exe run-script)."""
    if given:
        return (given,)
    return (sys.executable, RUN_SCRIPT) if host.frozen() else (sys.executable,)


def grants(given: List[str]) -> Tuple[Grant, ...]:
    try:
        return tuple(Grant.parse(text) for text in given)
    except ValueError as e:
        raise Mistyped(str(e)) from None


def script_text(info: ScriptInfo) -> str:
    ended = "" if info.status == RUNNING else f" (exit code {info.exit_code})"
    lines = [f"script {info.id} {info.name}: {info.status}{ended}", f"log {info.log}"]
    if info.allow:
        lines.append("may " + ", ".join(str(grant) for grant in info.allow))
    return "\n".join(lines)


def start_script(args, client: Client) -> int:
    started = client.call(
        StartScript(
            path=str(Path(args.file).resolve()),
            python=interpreter(args.python),
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
    """The file as Python runs it: __main__, its folder first on the path."""
    path = Path(args.file).resolve()
    sys.argv = [str(path), *args.passed]
    sys.path.insert(0, str(path.parent))
    runpy.run_path(str(path), run_name="__main__")
    return OK
