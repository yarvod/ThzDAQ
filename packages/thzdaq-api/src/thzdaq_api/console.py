"""A Python console of the window: what the window gives the kernel of each
console it opens.

The kernel is IPython's (ipykernel, thzdaq_api.kernel), a process of its own
that the window talks to over the Jupyter protocol: code that hangs or dies
there leaves the window and the daemon alone. It runs with the scripts' Python
(host.python_module: this interpreter from sources, a build's own), so it has
every module a script has. It is a client of the daemon as a script is: it
calls as console (thzdaq_api.origins), with the rights of a person's script,
in the window's workspace, on the window's daemon (the simulator's too).

IPython keeps the history of every console of the program in one base, in the
program's own folder (not the person's ~/.ipython: their startup files and
settings stay out of the bench's console).
"""

from pathlib import Path
from typing import Dict, List, Optional

from thzdaq_api import host
from thzdaq_api.origins import CONSOLE_ENV
from thzdaq_api.scripts import SIMULATE_ENV
from thzdaq_api.workspace import WORKSPACE_ENV

KERNEL = "thzdaq_api.kernel"  # the module the kernel runs
CONNECTION = "{connection_file}"  # where jupyter_client names the kernel's file
IPYTHON_DIR_ENV = "IPYTHONDIR"  # where IPython keeps its history and settings
# What a console runs as it opens, and again after each restart
OPENING = "from thzdaq import *\nlab = connect()"


def kernel_command(built: Optional[Path] = None) -> List[str]:
    """How the window starts a console's kernel; built: with that build's
    thzdaq-cli (the release checks its build so)."""
    if built is not None:
        return host.built_module(built, KERNEL, "-f", CONNECTION)
    return host.python_module(KERNEL, "-f", CONNECTION)


def history_dir() -> Path:
    """IPython's folder of the program's consoles, their one history; made
    when missing (IPython takes a temporary folder in place of one that is
    not there)."""
    found = host.user_dir() / "ipython"
    found.mkdir(parents=True, exist_ok=True)
    return found


def kernel_environment(simulate: bool, workspace: Optional[Path]) -> Dict[str, str]:
    """What the window adds to a kernel's environment: it calls as console,
    the window's daemon (simulate) and workspace, IPython's folder."""
    found = {
        CONSOLE_ENV: "1",
        SIMULATE_ENV: "1" if simulate else "0",
        IPYTHON_DIR_ENV: str(history_dir()),
    }
    if workspace is not None:
        found[WORKSPACE_ENV] = str(workspace)
    return found


def run_file(path: Path) -> str:
    """The code that runs a script in a console as IPython's %run does: as
    __main__, its names left in the console to look at."""
    return f'%run "{Path(path).as_posix()}"'
