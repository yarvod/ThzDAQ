"""thzdaq daemon …: the daemon itself — what it holds, starting it (in the
background, or in this terminal with its log here), stopping and restarting
it, killing one that does not answer, its log, its clients, a queue that
hangs, its settings. thzdaq serve runs it in this terminal."""

import subprocess
import sys
import time
from typing import List

from thzdaq_api import host
from thzdaq_api.daemon import (
    DaemonSettings,
    DaemonStatus,
    GetDaemonSettings,
    GetDaemonStatus,
    ReadDaemonLog,
    ResetLane,
    RestartDaemon,
    SetDaemonSettings,
    StopDaemon,
    StopMode,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import ListRuns
from thzdaq_api.measurement_file import RUNNING

from thzdaq_cli import show
from thzdaq_cli.client import FAILED, KIND, OK, Client, origin

FOLLOW_S = 0.5  # how often a followed log is looked at


def add(commands) -> None:
    group = commands.add_parser("daemon", help="the daemon: status, start, stop, log")
    actions = group.add_subparsers(dest="action", required=True, metavar="ACTION")
    actions.add_parser(
        "status", help="what it is and holds (exit 1: problems, 3: none runs)"
    ).set_defaults(run=status)
    start = actions.add_parser("start", help="start it unless it runs")
    start.add_argument("--station", help="the profile it loads when it starts")
    start.add_argument(
        "--foreground", action="store_true", help="in this terminal, its log here"
    )
    start.set_defaults(run=start_daemon)
    for name, what in (("stop", "stop it"), ("restart", "stop and start it again")):
        command = actions.add_parser(name, help=what)
        modes = command.add_mutually_exclusive_group()
        modes.add_argument(
            "--cancel",
            action="store_true",
            help="end running measurements (they restore), then the safe state",
        )
        modes.add_argument(
            "--abort", action="store_true", help="also break reads that hang"
        )
        command.set_defaults(run=stop, restart=name == "restart")
    actions.add_parser("kill", help="end a daemon that does not answer").set_defaults(
        run=kill
    )
    logs = actions.add_parser("logs", help="its log")
    logs.add_argument("-n", "--lines", type=int, default=50)
    logs.add_argument("-f", "--follow", action="store_true", help="then follow it")
    logs.set_defaults(run=read_log)
    actions.add_parser("clients", help="who listens to it").set_defaults(run=clients)
    reset = actions.add_parser(
        "reset-lane", help="give an instrument that hangs a new queue"
    )
    reset.add_argument("instrument")
    reset.set_defaults(run=reset_lane)
    settings = actions.add_parser("settings", help="show or change its settings")
    settings.add_argument(
        "--idle-timeout",
        type=float,
        metavar="SECONDS",
        help="how long it waits with no client and no measurement; 0: never",
    )
    settings.set_defaults(run=change_settings)
    serve = commands.add_parser(
        "serve", help="the daemon in this terminal (daemon start --foreground)"
    )
    serve.add_argument("--station", help="the profile it loads")
    serve.set_defaults(run=start_daemon, foreground=True)


def status_text(status: DaemonStatus) -> str:
    process = status.process
    lines = [
        f"ThzDAQ {process.app_version} daemon{' (simulator)' if process.simulate else ''}"
        f", pid {process.pid}, port {process.port}, since {process.started}",
        f"profile {show.profile(status.station, status.path)}",
    ]
    sections = (
        ("clients", ("kind", "origin", "pid", "since"),
         [(c.kind, c.origin, c.pid, c.since) for c in status.clients]),
        ("measurements", ("id", "title", "done", "origin"),
         [(r.id, r.title, f"{r.done}/{r.total or '?'}", r.origin) for r in status.runs]),
        ("queues", ("instrument", "waiting", "running", "for"),
         [(q.instrument, q.pending, q.current or "", f"{q.busy_for:.0f} s")
          for q in status.lanes if q.pending or q.current]),
        ("connections", ("connection", "state", "instruments"),
         [(c.label, "broken" if c.broken else "open" if c.open else "closed",
           ", ".join(c.instruments)) for c in status.connections]),
        ("polls", ("device", "every", "subscribers"),
         [(p.ref, f"{p.interval:g} s", p.subscribers) for p in status.polls]),
    )  # fmt: skip
    for title, headers, rows in sections:
        text = show.table(headers, rows)
        if text:
            lines += ["", f"{title}:", text]
    if status.problems:
        lines += ["", "problems:", *status.problems]
    return "\n".join(lines)


def status(args, client: Client) -> int:
    found = client.running_lab().call(GetDaemonStatus())
    client.out(found, status_text)
    return FAILED if found.problems else OK


def start_daemon(args, client: Client) -> int:
    if args.foreground:
        given = ["--station", args.station] if args.station else []
        given += ["--simulate"] if client.simulate else []
        try:
            return subprocess.call([*host.start_command(), *given])
        except KeyboardInterrupt:
            return OK  # the daemon heard it too and stops
    try:
        lab = client.running_lab()
        print("the daemon runs already")
    except LabError as e:
        if e.code != ErrorCode.UNREACHABLE:
            raise
        lab = host.connect_or_start(client.simulate, args.station, origin(), KIND)
        print("the daemon started")
    client.out(
        lab.call(GetDaemonStatus()).process, lambda p: f"pid {p.pid}, port {p.port}"
    )
    return OK


def stop(args, client: Client) -> int:
    mode = StopMode.ABORT if args.abort else StopMode.CANCEL if args.cancel else None
    lab = client.running_lab()
    if mode is not None:
        running = [r for r in lab.call(ListRuns()) if r.status == RUNNING]
        question = f"End {len(running)} running measurement(s)?"
        if running and not client.ask(question):
            return FAILED
    operation = RestartDaemon if args.restart else StopDaemon
    lab.call(operation(mode=mode or StopMode.GRACEFUL))
    print("the daemon restarts" if args.restart else "the daemon stops")
    return OK


def kill(args, client: Client) -> int:
    killed = host.kill(client.simulate)
    print(f"ended pid {killed}" if killed else "no daemon ran")
    return OK


def read_log(args, client: Client) -> int:
    try:
        lines: List[str] = list(
            client.running_lab().call(ReadDaemonLog(lines=args.lines))
        )
    except LabError as e:  # a daemon that ended left its log: why it did
        if e.code != ErrorCode.UNREACHABLE:
            raise
        files = host.DaemonFiles.of(client.simulate)
        lines = host.log_tail(files, args.lines).splitlines()
    print("\n".join(lines))
    if args.follow:
        follow(host.DaemonFiles.of(client.simulate).log)
    return OK


def follow(path) -> None:
    """What the log gets from now on, until Ctrl+C."""
    seen = path.stat().st_size if path.exists() else 0
    try:
        while True:
            time.sleep(FOLLOW_S)  # the log is another process's file: look again
            size = path.stat().st_size if path.exists() else 0
            if size < seen:
                seen = 0  # moved aside at a start: a new log
            if size > seen:
                with open(path, "rb") as log:
                    log.seek(seen)
                    sys.stdout.write(log.read().decode("utf-8", errors="replace"))
                    sys.stdout.flush()
                seen = size
    except KeyboardInterrupt:
        pass


def clients(args, client: Client) -> int:
    found = client.running_lab().call(GetDaemonStatus()).clients
    client.out(
        found,
        lambda c: show.table(
            ("kind", "origin", "pid", "since"),
            [(i.kind, i.origin, i.pid, i.since) for i in c],
        )
        or "no client",
    )
    return OK


def reset_lane(args, client: Client) -> int:
    question = f"Break the commands of {args.instrument} and give it a new queue?"
    if not client.ask(question):
        return FAILED
    had = client.running_lab().call(ResetLane(instrument=args.instrument))
    print("a new queue" if had else f"{args.instrument} had no queue")
    return OK


def change_settings(args, client: Client) -> int:
    lab = client.running_lab()
    if args.idle_timeout is None:
        found = lab.call(GetDaemonSettings())
    else:
        found = lab.call(SetDaemonSettings(idle_timeout=args.idle_timeout))
    client.out(found, settings_text)
    return OK


def settings_text(settings: DaemonSettings) -> str:
    idle = settings.idle_timeout
    return f"idle timeout: {f'{idle:g} s' if idle else 'never'}"
