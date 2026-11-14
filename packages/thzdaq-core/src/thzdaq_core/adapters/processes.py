"""Processes the daemon starts apart (the Launcher port): a script's process
leaves the daemon's session and terminal, its output goes to its log."""

import os
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence

from thzdaq_api.host import apart


class Process:
    def __init__(self, popen: subprocess.Popen):
        self.popen = popen
        self.pid = popen.pid

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        try:
            return self.popen.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        self.popen.kill()


class Processes:
    def launch(
        self,
        command: Sequence[str],
        folder: Path,
        environment: Mapping[str, str],
        log: Path,
        removed: Sequence[str] = (),
    ) -> Process:
        log.parent.mkdir(parents=True, exist_ok=True)
        inherited = {k: v for k, v in os.environ.items() if k not in removed}
        with open(log, "ab") as output:
            return Process(
                subprocess.Popen(
                    list(command),
                    cwd=folder,
                    env={**inherited, **environment},
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    **apart(),
                )
            )
