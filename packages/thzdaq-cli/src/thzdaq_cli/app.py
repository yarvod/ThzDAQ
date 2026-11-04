"""thzdaq: the bench from the terminal, a client of the daemon as the GUI is.

Every command calls the daemon of the instruments (--simulate: of their
simulator) and starts it when none runs, saying so in one line on stderr. A
change that may harm the bench, or that touches a device a measurement sweeps,
is asked in the terminal; --yes answers yes, and without a terminal the
answer is no. --json prints what the daemon answered, as JSON.

Arguments after -- are not thzdaq's: they go to the script a command runs.

Exit codes: 0 done, 1 refused or failed, 2 wrong arguments, 3 no daemon runs.
"""

import argparse
import sys
from typing import List, Optional, Tuple

from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_cli import (
    agents,
    approvals,
    daemon,
    devices,
    measurements,
    scripts,
    station,
)
from thzdaq_cli.client import (
    FAILED,
    KIND,
    NO_DAEMON,
    PROG,
    USAGE,
    Client,
    Connect,
    Mistyped,
    reach,
)

PASSED = "--"  # what follows is the script's


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(
        prog=PROG,
        description="The ThzDAQ bench from the terminal (a client of its daemon)",
        epilog="Exit codes: 0 done, 1 refused or failed, 2 wrong arguments, "
        "3 no daemon runs.",
    )
    found.add_argument("--simulate", action="store_true", help="the simulator's daemon")
    found.add_argument("--json", action="store_true", help="answers as JSON")
    found.add_argument(
        "-y", "--yes", action="store_true", help="answer yes to questions"
    )
    found.add_argument(
        "--no-autostart",
        action="store_true",
        help="do not start the daemon when none runs",
    )
    found.set_defaults(kind=KIND)
    commands = found.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for area in (daemon, devices, measurements, scripts, station, approvals, agents):
        area.add(commands)
    return found


def passed_on(argv: List[str]) -> Tuple[List[str], List[str]]:
    """thzdaq's own arguments, and those after -- for the script it runs."""
    if PASSED not in argv:
        return argv, []
    at = argv.index(PASSED)
    return argv[:at], argv[at + 1 :]


def main(argv: Optional[List[str]] = None, connect: Connect = reach) -> int:
    own, passed = passed_on(sys.argv[1:] if argv is None else list(argv))
    args = parser().parse_args(own)
    args.passed = passed
    client = Client(args, connect)
    try:
        return args.run(args, client)
    except LabError as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return NO_DAEMON if e.code == ErrorCode.UNREACHABLE else FAILED
    except Mistyped as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return USAGE
    except KeyboardInterrupt:
        return 130
