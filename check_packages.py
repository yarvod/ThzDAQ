"""Install the built packages as a user gets them, each time into a clean environment.

    uv build --all-packages -o dist/packages
    uv run --package thzdaq-api python check_packages.py dist/packages [--tag v0.3.0-beta.1]

- every package of packages/ is built, wheel and sdist, at the program's
  version (and the tag's, when given); its wheel holds every file of its source;
- thzdaq alone is the light client: exactly thzdaq, thzdaq-api, thzdaq-cli and
  msgspec (no numpy, no drivers), on the oldest and the newest Python; the
  thzdaq command answers and `from thzdaq import connect` imports;
- thzdaq[all] brings every package at that version; their commands answer, and
  the daemon it brings starts on simulators, answers and stops.

The packages of ThzDAQ come only from the folder, given as files: PyPI may
already have that version (a release built again with release.py --again).
The release workflow runs it before publishing (.github/workflows/release.yml).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set

from thzdaq_api.host import DIR_ENV
from thzdaq_api.origins import AGENT_SHELLS

from release import ROOT, VERSION_FILE, program_version, projects, python_version

LIGHT = {"thzdaq", "thzdaq-api", "thzdaq-cli", "msgspec"}
LIGHT_PYTHONS = ("3.11", "3.13")
ALL_PYTHON = "3.11"  # thzdaq-gui is built and tested on it


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class Failed(Exception):
    pass


def run(*command: str, cwd: Path, env: Dict[str, str]) -> str:
    done = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=600
    )
    if done.returncode != 0:
        raise Failed(
            f"{' '.join(command)} exited with {done.returncode}\n"
            f"{done.stdout}{done.stderr}"
        )
    return done.stdout


class Built:
    """The wheels and sdists in a folder, one of each per package."""

    def __init__(self, folder: Path):
        self.wheels: Dict[str, Path] = {}
        self.versions: Dict[str, str] = {}
        for wheel in sorted(folder.glob("*.whl")):
            name, version = wheel.name.split("-")[:2]
            self.wheels[canonical(name)] = wheel
            self.versions[canonical(name)] = version
        self.sdists = {
            canonical(sdist.name[: -len(".tar.gz")].rsplit("-", 1)[0])
            for sdist in folder.glob("*.tar.gz")
        }

    def check(self, version: str) -> None:
        sources = {
            canonical(project.parent.name): project for project in projects(ROOT)
        }
        if set(self.wheels) != set(sources) or self.sdists != set(sources):
            raise Failed(
                f"built wheels {sorted(self.wheels)} and sdists {sorted(self.sdists)}, "
                f"packages/ has {sorted(sources)}"
            )
        wrong = {n: v for n, v in self.versions.items() if v != version}
        if wrong:
            raise Failed(f"built at another version than {version}: {wrong}")
        for name, project in sources.items():
            missing = sources_of(project.parent) - set(
                zipfile.ZipFile(self.wheels[name]).namelist()
            )
            if missing:
                raise Failed(f"the wheel of {name} lacks {sorted(missing)}")

    def requirement(self, name: str, extras: str = "") -> str:
        return f"{name}{extras} @ {self.wheels[name].resolve().as_uri()}"


def sources_of(package: Path) -> Set[str]:
    """The files of a package's source as its wheel names them."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "src"],
        cwd=package,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        Path(path).relative_to("src").as_posix() for path in listed.split("\0") if path
    }


class Environment:
    """A new virtual environment with nothing of this repository in reach."""

    def __init__(self, folder: Path, python: str):
        # A person's terminal: in an agent's shell the command line acts for
        # the agent; and this environment's Python, not the one running here
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", *AGENT_SHELLS)
        }
        # Its daemon's host files apart from a daemon running on this machine
        self.env[DIR_ENV] = str(folder / "daemon")
        self.home = folder / "home"
        self.home.mkdir(parents=True)
        self.uv("venv", "--quiet", "--python", python, str(folder / "venv"))
        self.scripts = folder / "venv" / ("Scripts" if os.name == "nt" else "bin")
        self.python = self.scripts / ("python.exe" if os.name == "nt" else "python")

    def uv(self, *arguments: str) -> str:
        return run("uv", *arguments, cwd=self.home, env=self.env)

    def install(self, *requirements: str) -> None:
        self.uv(
            "pip", "install", "--quiet", "--python", str(self.python), *requirements
        )

    def distributions(self) -> Dict[str, str]:
        listed = self.uv(
            "pip", "list", "--python", str(self.python), "--format", "json"
        )
        return {canonical(d["name"]): d["version"] for d in json.loads(listed)}

    def command(self, program: str, *arguments: str) -> str:
        return run(str(self.scripts / program), *arguments, cwd=self.home, env=self.env)

    def python_runs(self, code: str) -> None:
        run(str(self.python), "-I", "-c", code, cwd=self.home, env=self.env)


def check_light(built: Built, folder: Path, python: str) -> None:
    env = Environment(folder, python)
    env.install(
        *(built.requirement(name) for name in ("thzdaq", "thzdaq-api", "thzdaq-cli"))
    )
    found = env.distributions()
    if set(found) != LIGHT:
        raise Failed(
            f"thzdaq on Python {python} brings {sorted(found)}, not {sorted(LIGHT)}"
        )
    env.command("thzdaq", "--help")
    env.python_runs("from thzdaq import connect")


def check_all(built: Built, folder: Path, version: str) -> None:
    env = Environment(folder, ALL_PYTHON)
    others = [built.requirement(name) for name in built.wheels if name != "thzdaq"]
    env.install(built.requirement("thzdaq", "[all]"), *others)
    found = env.distributions()
    wrong = {n: found.get(n) for n in built.wheels if found.get(n) != version}
    if wrong:
        raise Failed(f"thzdaq[all] brings {wrong}, not {version}")
    # The window's package without Qt: a runner of CI may lack the libraries Qt needs
    modules = [n.replace("-", "_") for n in built.wheels if n != "thzdaq-gui"]
    env.python_runs("; ".join(f"import {m}" for m in [*modules, "thzdaq_gui.version"]))
    env.command("thzdaq", "mcp", "--help")
    env.command("thzdaq-daemon", "--help")
    env.command("thzdaq-station", "--help")
    for action in ("start", "status", "stop"):
        env.command("thzdaq", "--simulate", "daemon", action)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="where uv build put the packages")
    parser.add_argument(
        "--tag", default="", help="the release tag they are built for (empty: none)"
    )
    args = parser.parse_args(argv)
    version = python_version(program_version(VERSION_FILE))
    try:
        if args.tag and python_version(args.tag.lstrip("v")) != version:
            raise Failed(f"version.py has {version}, the tag is {args.tag}")
        built = Built(args.folder)
        built.check(version)
        print(f"built: {len(built.wheels)} packages at {version}")
        with tempfile.TemporaryDirectory(prefix="thzdaq-packages-") as temporary:
            for python in LIGHT_PYTHONS:
                check_light(built, Path(temporary) / f"light-{python}", python)
                print(f"thzdaq on Python {python}: {', '.join(sorted(LIGHT))}; it runs")
            check_all(built, Path(temporary) / "all", version)
            print(f"thzdaq[all] on Python {ALL_PYTHON}: every package; the daemon runs")
    except (Failed, ValueError) as failure:  # ValueError: a tag that is no version
        print(f"check_packages: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
