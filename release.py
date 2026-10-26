"""Cut a release: stamp the version, commit, tag vX.Y.Z and push; CI builds and publishes it.

    uv run python release.py 0.3.0          # release
    uv run python release.py 0.3.0-rc.1     # pre-release
    uv run python release.py 0.3.0 --no-push
    uv run python release.py 0.3.0 --again  # build the same tag again after fixes

--again moves the existing tag to the current commit and pushes it again: CI
tests and builds it once more and replaces the files of the GitHub release.
Who already installed that version is not offered the corrected build (the
version is the same); release a new version once people have installed it.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).parent / "packages/thzdaq-gui/src/thzdaq_gui/version.py"
VERSION = re.compile(r"^\d+\.\d+\.\d+(-(rc|beta|alpha)\.\d+)?$")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="X.Y.Z or X.Y.Z-rc.N")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument(
        "--again",
        action="store_true",
        help="move the existing tag to the current commit and build it again",
    )
    args = parser.parse_args()
    version = args.version.lstrip("v")
    if not VERSION.match(version):
        parser.error(f"{args.version!r} is not X.Y.Z[-rc.N]")
    tag = f"v{version}"
    if git("status", "--porcelain"):
        parser.error("commit or stash your changes first")
    if args.again:
        return again(parser, version, tag, push=not args.no_push)
    if git("tag", "--list", tag):
        parser.error(f"tag {tag} already exists (--again builds it again)")

    text = VERSION_FILE.read_text(encoding="utf-8")
    text = re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"', text)
    VERSION_FILE.write_text(text, encoding="utf-8")
    git("add", str(VERSION_FILE))
    git("commit", "-m", f"release {tag}")
    git("tag", "-a", tag, "-m", f"ThzDAQ {tag}")
    print(f"tagged {tag} on {git('rev-parse', '--abbrev-ref', 'HEAD')}")
    if not args.no_push:
        # A tag pushed together with its branch may not start the release workflow
        subprocess.run(["git", "push"], check=True)
        subprocess.run(["git", "push", "origin", tag], check=True)
        print("pushed; GitHub Actions builds the Windows release")
    return 0


def again(parser, version: str, tag: str, push: bool) -> int:
    """The same version from the current commit: the tag moves, CI rebuilds it."""
    if not git("tag", "--list", tag):
        parser.error(f"tag {tag} does not exist yet: release it without --again")
    stamped = re.search(r'__version__ = "([^"]*)"', VERSION_FILE.read_text("utf-8"))
    if stamped is None or stamped.group(1) != version:
        found = stamped.group(1) if stamped else "no version"
        parser.error(f"version.py has {found}: --again rebuilds {tag} only")
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
        print("pushed; GitHub Actions builds the release again and replaces its files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
