"""python -m thzdaq_daemon (thzdaq-daemon; a built ThzDAQ.exe --serve): the bench
daemon. Clients start it themselves (thzdaq_api.host.connect_or_start); by hand
it runs in the terminal with its log there."""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from thzdaq_api.host import DaemonFiles, program_dir

from thzdaq_daemon.process import Daemon, Options


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="thzdaq-daemon", description="ThzDAQ bench daemon"
    )
    parser.add_argument(
        "--home",
        help="its folder: daemon.json and data/ (default: the program's folder)",
    )
    parser.add_argument("--station", help="the bench profile to work with, a YAML file")
    parser.add_argument("--data", help="measurements folder (default: data/ in home)")
    parser.add_argument(
        "--simulate", action="store_true", help="the simulator daemon: no instruments"
    )
    parser.add_argument("--port", type=int, default=0, help="0: any free port")
    parser.add_argument(
        "--idle-timeout",
        type=float,
        help="seconds without clients and measurements before it ends; 0: never",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        # Lanes and runs are threads: the log names them
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    options = Options(
        home=Path(args.home) if args.home else program_dir(),
        files=DaemonFiles.of(args.simulate),
        station=args.station,
        data=Path(args.data) if args.data else None,
        simulate=args.simulate,
        port=args.port,
        idle_timeout=args.idle_timeout,
    )
    return Daemon(options).run()


if __name__ == "__main__":
    sys.exit(main())
