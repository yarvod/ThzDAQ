"""Cut a release: stamp the version, commit, tag vX.Y.Z and push; CI builds and publishes it.

    uv run python release.py 0.3.0          # release
    uv run python release.py 0.3.0-beta.1   # pre-release: beta.2 for the next one
    uv run python release.py 0.3.0-rc.1     # pre-release
    uv run python release.py 0.3.0 --no-push
    uv run python release.py 0.3.0 --again  # build the same tag again after fixes

The version goes to the program (thzdaq_gui/version.py, as the tag spells it)
and to every package in packages/ as Python spells it (PEP 440: 0.3.0-beta.1
is 0.3.0b1); the packages require each other at exactly that version, and
uv.lock follows. CI publishes the build on GitHub and the packages on PyPI.

--again moves the existing tag to the current commit and pushes it again: CI
tests and builds it once more and replaces the files of the GitHub release.
PyPI keeps the packages it got first: a version there never changes. Who
already installed that version is not offered the corrected build (the
version is the same); release a new version once people have installed it.
"""

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import List

ROOT = Path(__file__).parent
VERSION_FILE = ROOT / "packages/thzdaq-gui/src/thzdaq_gui/version.py"
VERSION = re.compile(r"^(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?$")
# Pre-releases as Python spells them (PEP 440)
PRE = {"alpha": "a", "beta": "b", "rc": "rc"}
PROGRAM_VERSION = re.compile(r'__version__ = "([^"]*)"')
PROJECT_VERSION = re.compile(r'^version = "[^"]*"', re.MULTILINE)
# A requirement on a package of ThzDAQ, pinned or not: "thzdaq-api", "thzdaq-api==0.3.0"
PIN = re.compile(r'"(thzdaq(?:-[a-z]+)?)(?:==[^"]*)?"')


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def python_version(version: str) -> str:
    """The packages' version for the program's X.Y.Z[-beta.N]: X.Y.Z[bN]."""
    match = VERSION.match(version)
    if match is None:
        raise ValueError(f"{version!r} is not X.Y.Z[-beta.N|-rc.N|-alpha.N]")
    release, pre, number = match.groups()
    return release if pre is None else f"{release}{PRE[pre]}{number}"


def projects(root: Path) -> List[Path]:
    """The pyproject.toml of every package published on PyPI."""
    return sorted(root.glob("packages/*/pyproject.toml"))


def program_version(program: Path) -> str:
    """The version stamped in version.py, empty when there is none."""
    stamped = PROGRAM_VERSION.search(program.read_text("utf-8"))
    return stamped.group(1) if stamped else ""


def project_version(project: Path) -> str:
    return tomllib.loads(project.read_text("utf-8"))["project"]["version"]


def stamp(program: Path, packages: List[Path], version: str) -> None:
    """Write the version to the program and to every package with its pins."""
    text = program.read_text("utf-8")
    program.write_text(
        PROGRAM_VERSION.sub(f'__version__ = "{version}"', text), encoding="utf-8"
    )
    pinned = python_version(version)
    for project in packages:
        text = PROJECT_VERSION.sub(
            f'version = "{pinned}"', project.read_text("utf-8"), count=1
        )
        # Every requirement on another package of ThzDAQ; the name line stays
        lines = [
            line if line.startswith("name =") else PIN.sub(rf'"\1=={pinned}"', line)
            for line in text.splitlines(keepends=True)
        ]
        project.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="X.Y.Z or X.Y.Z-beta.N, X.Y.Z-rc.N")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument(
        "--again",
        action="store_true",
        help="move the existing tag to the current commit and build it again",
    )
    args = parser.parse_args()
    version = args.version.lstrip("v")
    if not VERSION.match(version):
        parser.error(f"{args.version!r} is not X.Y.Z[-beta.N|-rc.N|-alpha.N]")
    tag = f"v{version}"
    if git("status", "--porcelain"):
        parser.error("commit or stash your changes first")
    if args.again:
        return again(parser, version, tag, push=not args.no_push)
    if git("tag", "--list", tag):
        parser.error(f"tag {tag} already exists (--again builds it again)")

    packages = projects(ROOT)
    stamp(VERSION_FILE, packages, version)
    # The lock names the version of every package of the workspace
    subprocess.run(["uv", "lock"], check=True, cwd=ROOT)
    git("add", str(VERSION_FILE), *map(str, packages), str(ROOT / "uv.lock"))
    git("commit", "-m", f"release {tag}")
    git("tag", "-a", tag, "-m", f"ThzDAQ {tag}")
    print(f"tagged {tag} on {git('rev-parse', '--abbrev-ref', 'HEAD')}")
    if not args.no_push:
        # A tag pushed together with its branch may not start the release workflow
        subprocess.run(["git", "push"], check=True)
        subprocess.run(["git", "push", "origin", tag], check=True)
        print("pushed; GitHub Actions builds the Windows release and the packages")
    return 0


def again(parser, version: str, tag: str, push: bool) -> int:
    """The same version from the current commit: the tag moves, CI rebuilds it."""
    if not git("tag", "--list", tag):
        parser.error(f"tag {tag} does not exist yet: release it without --again")
    found = program_version(VERSION_FILE) or "no version"
    if found != version:
        parser.error(f"version.py has {found}: --again rebuilds {tag} only")
    for project in projects(ROOT):
        if project_version(project) != python_version(version):
            parser.error(
                f"{project.parent.name} has {project_version(project)}: "
                f"--again rebuilds {tag} only"
            )
    old = git("rev-list", "-n", "1", tag)
    head = git("rev-parse", "HEAD")
    if old == head:
        print(f"{tag} is already on this commit; pushing it again rebuilds it")
    git("tag", "-f", "-a", tag, "-m", f"ThzDAQ {tag}")
    print(
        f"moved {tag}: {old[:7]} -> {head[:7]} on {git('rev-parse', '--abbrev-ref', 'HEAD')}"
    )
    if push:
        subprocess.run(["git", "push"], check=True)
        subprocess.run(["git", "push", "--force", "origin", tag], check=True)
        print(
            "pushed; GitHub Actions builds the release again and replaces its files "
            "(PyPI keeps the packages it has)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
