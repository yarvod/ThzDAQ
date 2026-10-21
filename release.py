"""Cut a release: stamp the version, commit, tag vX.Y.Z and push; CI builds and publishes it.

    uv run python release.py 0.3.0          # release
    uv run python release.py 0.3.0-rc.1     # pre-release
    uv run python release.py 0.3.0 --no-push
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
    args = parser.parse_args()
    version = args.version.lstrip("v")
    if not VERSION.match(version):
        parser.error(f"{args.version!r} is not X.Y.Z[-rc.N]")
    tag = f"v{version}"
    if git("status", "--porcelain"):
        parser.error("commit or stash your changes first")
    if git("tag", "--list", tag):
        parser.error(f"tag {tag} already exists")

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


if __name__ == "__main__":
    sys.exit(main())
