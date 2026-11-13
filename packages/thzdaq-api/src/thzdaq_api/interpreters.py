"""The Python a workspace's scripts run with: its scripts started by the
daemon (thzdaq script start), the bench's own measurements started from it,
and the kernels of the window's consoles.

A workspace names it in thzdaq.toml (python): an environment's folder or its
interpreter, relative to the workspace or absolute. A workspace that names
none, and the program's own folder, run them with the program's own Python
(host.script_python: this interpreter from sources, a build's own through
thzdaq-cli run-script). This module is the one owner of that rule: whoever
starts a script asks it with the workspace the script runs in (the daemon
with the one the operation names, the window with its own).

A person chooses among the environments found here: the workspace's .venv
(or the nearest one above it, as uv finds a project's), uv's tool
environments, conda's; or any interpreter. A chosen one is checked: that it
runs, its Python, and that it has thzdaq of exactly this program's version.
The packages of ThzDAQ require each other at one version, and a script's
contract with the daemon (its declarations, its inputs, the console's kernel)
changes with it, beyond what the daemon's API_VERSION tells. A console's
kernel also needs ipykernel there.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from importlib import util
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import msgspec

from thzdaq_api import host
from thzdaq_api.daemon import API_VERSION
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.workspace import FILE, PathLike, read

PACKAGE = "thzdaq"  # what a person installs, and a script imports
CONTRACT = "thzdaq-api"  # the package whose version is the program's
KERNEL_PACKAGE = "ipykernel"  # what a console's kernel needs besides
VENV = ".venv"  # the folder of a project's environment, as uv makes it
CHECK_S = 20.0  # an interpreter answers within this (a first start is slow)
FIND_S = 20.0  # uv and conda list their environments within this
CONDA_ENV = "CONDA_EXE"  # where conda's shells put conda itself
OLDEST = (3, 11)  # the Python thzdaq needs at least (requires-python)

# Kinds of environments, as people see them
OWN, PROJECT, UV, CONDA, CHOSEN = "built-in", "venv", "uv", "conda", "path"

# What a checked interpreter tells of itself: one JSON line
PROBE = f"""\
import json, platform
from importlib import metadata, util
told = {{"version": platform.python_version()}}
try:
    import {PACKAGE}
    from thzdaq_api.daemon import API_VERSION
    told["thzdaq"] = metadata.version({CONTRACT!r})
    told["api"] = API_VERSION
except Exception as e:
    told["missing"] = f"{{type(e).__name__}}: {{e}}"
told["console"] = util.find_spec({KERNEL_PACKAGE!r}) is not None
print(json.dumps(told))
"""


def python_in(path: PathLike) -> Path:
    """The interpreter of an environment's folder (a venv's, a conda one's),
    or the interpreter given; LabError NOT_FOUND when there is none."""
    path = Path(path).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        for inside in _interpreters(path):
            if inside.is_file():
                return inside
        raise LabError(
            ErrorCode.NOT_FOUND,
            f"No Python in {path}",
            "name an environment's folder (.venv) or its interpreter",
        )
    raise LabError(ErrorCode.NOT_FOUND, f"No Python at {path}: it is not there")


def _interpreters(folder: Path) -> Tuple[Path, ...]:
    """Where an environment keeps its interpreter: a venv's Scripts\\ on
    Windows and bin/ elsewhere; a conda one's at its top on Windows."""
    if sys.platform == "win32":
        return (folder / "Scripts" / "python.exe", folder / "python.exe")
    return (folder / "bin" / "python3", folder / "bin" / "python")


def chosen(folder: Optional[PathLike]) -> Optional[Path]:
    """The interpreter a workspace names; None when it names none (or for no
    workspace: the program's own folder). LabError when its thzdaq.toml is
    broken or names one that is not there."""
    if folder is None:
        return None
    named = read(folder).python
    if not named:
        return None
    try:
        return python_in(Path(folder) / Path(named).expanduser())
    except LabError as e:
        raise LabError(
            e.code,
            f"{Path(folder) / FILE} names the Python {named!r}: {e.message}",
            "choose another: File → Workspace settings, or thzdaq python set",
        ) from None


def scripts_python(folder: Optional[PathLike]) -> Tuple[str, ...]:
    """How a script of a workspace runs: [its interpreter], else the program's
    own (host.script_python), as a command the file and its arguments
    follow."""
    found = chosen(folder)
    return (str(found),) if found is not None else host.script_python()


def module_command(
    folder: Optional[PathLike], module: str, *arguments: str
) -> List[str]:
    """How a module runs as a program with a workspace's Python (python -m
    module arguments; a console's kernel)."""
    found = chosen(folder)
    if found is None:
        return host.python_module(module, *arguments)
    return [str(found), "-m", module, *arguments]


def located(path: PathLike) -> Path:
    """Where a Python typed here is: absolute, the links to it followed but
    not its own (a venv's interpreter links to the Python it was made from,
    which runs without the venv)."""
    path = Path(os.path.abspath(Path(path).expanduser()))
    return path.parent.resolve() / path.name


def stored(folder: PathLike, path: PathLike) -> str:
    """How thzdaq.toml names a Python typed here: relative to the workspace
    when it is in it (the folder moves with it), else absolute."""
    path = located(path)
    try:
        return path.relative_to(Path(folder).resolve()).as_posix()
    except ValueError:
        return str(path)


# The environments a person chooses among
class Environment(msgspec.Struct, frozen=True):
    """An environment found here: what kind, how a person knows it, its
    folder ("" for the program's own)."""

    kind: str
    name: str
    path: str = ""

    @property
    def own(self) -> bool:
        """The program's own Python."""
        return not self.path

    def interpreter(self) -> Optional[Path]:
        """Its interpreter (None: the program's own); one that is not there
        is where it would be."""
        if self.own:
            return None
        try:
            return python_in(self.path)
        except LabError:
            return Path(self.path)

    def runs(self, interpreter: Optional[Path]) -> bool:
        """Whether it is the environment of an interpreter (None: the
        program's own)."""
        mine = self.interpreter()
        if mine is None or interpreter is None:
            return mine is None and interpreter is None
        try:
            return mine.samefile(interpreter)
        except OSError:  # one of them is not there
            return False


def own() -> Environment:
    """The program's own Python."""
    return Environment(OWN, f"the program's own (Python {python_version()})")


def python_version() -> str:
    return platform.python_version()


def environments(
    folder: Optional[PathLike],
    conda: Optional[Sequence[str]] = None,
    uv: Optional[Sequence[str]] = None,
) -> Tuple[Environment, ...]:
    """The program's own first, then the workspace's .venv (and those above
    it), uv's tool environments, conda's, each once, and last the one the
    workspace names when it is none of them. conda, uv: how they are run
    (None: found here, () for none); one that fails finds nothing."""
    found: List[Environment] = [own()]
    if folder is not None:
        found += projects(Path(folder))
    found += uv_tools(uv_command() if uv is None else uv)
    found += conda_environments(conda_command() if conda is None else conda)
    seen, unique = set(), []
    for environment in found:
        key = os.path.normcase(environment.path)
        if key not in seen:
            seen.add(key)
            unique.append(environment)
    named = named_environment(folder)
    if named is not None and not any(e.runs(named.interpreter()) for e in unique):
        unique.append(named)
    return tuple(unique)


def current(
    found: Sequence[Environment], folder: Optional[PathLike]
) -> Optional[Environment]:
    """The one of found that a workspace's scripts run with (environments()
    lists it): the program's own when it names none."""
    named = named_environment(folder)
    if named is None:
        return next((e for e in found if e.own), None)
    interpreter = named.interpreter()
    return next((e for e in found if e == named or e.runs(interpreter)), None)


def named_environment(folder: Optional[PathLike]) -> Optional[Environment]:
    """The Python a workspace names, as it names it (it may not be there);
    None when it names none."""
    named = read(folder).python if folder is not None else ""
    if not named:
        return None
    return Environment(CHOSEN, named, str(Path(folder) / Path(named).expanduser()))


def projects(folder: Path) -> List[Environment]:
    """The .venv of the folder, and of each folder above it."""
    found = []
    here = folder.resolve()
    for above in (here, *here.parents):
        venv = above / VENV
        if any(inside.is_file() for inside in _interpreters(venv)):
            name = VENV if above == here else f"{above.name}/{VENV}"
            found.append(Environment(PROJECT, name, str(venv)))
    return found


def uv_command() -> Sequence[str]:
    found = shutil.which("uv")
    return (found,) if found else ()


def conda_command() -> Sequence[str]:
    found = os.environ.get(CONDA_ENV) or shutil.which("conda")
    return (found,) if found else ()


def _asked(command: Sequence[str]) -> str:
    """What a program answered; "" when it did not (the environments it
    knows are not found then)."""
    try:
        done = subprocess.run(
            list(command), capture_output=True, text=True, timeout=FIND_S,
            stdin=subprocess.DEVNULL, **host.windowless(),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout if done.returncode == 0 else ""


def uv_tools(uv: Sequence[str]) -> List[Environment]:
    """The environments of uv's tools (uv tool install thzdaq makes one)."""
    if not uv:
        return []
    answered = _asked([*uv, "tool", "dir"]).strip()
    if not answered or not Path(answered).is_dir():
        return []
    return [
        Environment(UV, f"tool {tool.name}", str(tool))
        for tool in sorted(Path(answered).iterdir())
        if any(inside.is_file() for inside in _interpreters(tool))
    ]


def conda_environments(conda: Sequence[str]) -> List[Environment]:
    """conda's environments (conda env list): base by its folder, the others
    by their names."""
    if not conda:
        return []
    try:
        listed = json.loads(_asked([*conda, "env", "list", "--json"]) or "{}")
    except json.JSONDecodeError:
        return []
    found = []
    for path in listed.get("envs", []):
        folder = Path(path)
        name = folder.name if folder.parent.name == "envs" else str(folder)
        found.append(Environment(CONDA, name, str(folder)))
    return found


# A chosen one, checked
class Checked(msgspec.Struct, frozen=True):
    """What a Python is to the bench's scripts: its version, the thzdaq it
    has, whether a console's kernel runs there; problem: why scripts cannot
    run with it ("" when they can), hint: what mends it."""

    python: str  # the interpreter; "" for the program's own
    version: str = ""  # of Python; "" when it did not run
    thzdaq: str = ""  # its thzdaq's version; "" without one
    console: bool = False  # ipykernel is there
    problem: str = ""
    hint: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem

    def text(self) -> str:
        """One line for people."""
        if not self.ok:
            return f"{self.problem}: {self.hint}" if self.hint else self.problem
        told = f"Python {self.version}, {PACKAGE} {self.thzdaq}"
        if not self.console:
            needed = install(self.python, KERNEL_PACKAGE)
            told += f"; a console needs {KERNEL_PACKAGE}: {needed}"
        return told


def install(python: str, *packages: str) -> str:
    """How packages are installed into an interpreter ("": the program's own,
    from PyPI): by uv, or by its pip."""
    named = " ".join(f'"{package}"' for package in packages)
    if not python:
        return f"pip install {named} where thzdaq is installed"
    return (
        f'uv pip install --python "{python}" {named}, '
        f'or "{python}" -m pip install {named}'
    )


def wanted() -> str:
    """thzdaq as a script's interpreter needs it: this program's version."""
    return f"{PACKAGE}=={host.app_version()}"


def check_own() -> Checked:
    """The program's own Python: it runs here, with the program's thzdaq."""
    return Checked(
        "", python_version(), host.app_version(),
        util.find_spec(KERNEL_PACKAGE) is not None,
    )  # fmt: skip


def check(python: PathLike, timeout: float = CHECK_S) -> Checked:
    """Whether scripts run with an interpreter (or an environment's folder):
    it runs, has thzdaq of this program's version (and ipykernel for a
    console). Never raises: what is wrong is told. It runs in an empty
    folder: nothing there stands for a module it imports."""
    try:
        interpreter = str(python_in(python))
    except LabError as e:
        return Checked(str(python), problem=e.message, hint=e.hint)
    try:
        with tempfile.TemporaryDirectory() as empty:
            done = subprocess.run(
                [interpreter, "-c", PROBE], capture_output=True, text=True,
                timeout=timeout, stdin=subprocess.DEVNULL, cwd=empty,
                **host.windowless(),
            )  # fmt: skip
    except subprocess.TimeoutExpired:
        return Checked(interpreter, problem=f"It did not answer in {timeout:g} s")
    except OSError as e:
        return Checked(interpreter, problem=f"It does not run: {e}")
    try:
        told = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        why = (done.stderr or done.stdout).strip()[-500:]
        return Checked(interpreter, problem=f"It does not run as Python: {why}")
    return judged(interpreter, told)


def judged(interpreter: str, told: dict) -> Checked:
    """What scripts make of what an interpreter told of itself (PROBE)."""
    version, has, console = told["version"], told.get("thzdaq", ""), told["console"]
    found = Checked(interpreter, version, has, console)
    hint = f"install it there: {install(interpreter, wanted())}"
    if tuple(int(part) for part in version.split(".")[:2]) < OLDEST:
        oldest = ".".join(map(str, OLDEST))
        problem = f"Python {version} is older than {oldest}, which {PACKAGE} needs"
        hint = f"choose an environment with Python {oldest} or newer"
    elif not has:
        problem = f"Python {version} has no {PACKAGE} ({told.get('missing', '')})"
    elif told.get("api") != API_VERSION:
        problem = f"Its {PACKAGE} {has} speaks another contract than this program's"
    elif has != host.app_version() and host.app_version() != host.UNKNOWN:
        problem = f"Its {PACKAGE} is {has}, this program is {host.app_version()}"
    else:
        return found
    return msgspec.structs.replace(found, problem=problem, hint=hint)
