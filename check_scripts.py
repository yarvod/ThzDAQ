"""Check that a build's own Python has what scripts import: what every example
imports and the modules script_modules.py names that this Python imports
here (the sources of the same version, on the same system). They are
imported with this Python from sources, or with a build's thzdaq-cli
run-script (the release checks its build so):

    uv run python check_scripts.py [dist/ThzDAQ/thzdaq-cli.exe]

Its arguments go after the file as python takes them (thzdaq-cli run-script
x.py a b), so this checks that too.
"""

import argparse
import ast
import importlib
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

IMPORT = "--import"  # the build's side: import these, print those that fail

# The build's side imports only what it is told to: what this side needs is
# imported where it is used


def imported(text: str) -> List[str]:
    """The modules a script imports by name."""
    found = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.append(node.module)
    return found


def failing(names: Iterable[str]) -> List[str]:
    failed = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as e:  # what a script would meet on its import
            failed.append(f"{name}: {type(e).__name__}: {e}")
    return failed


def expected() -> List[str]:
    """What the examples import, and the modules of script_modules that this
    Python imports: other systems' are not expected."""
    import script_modules
    from thzdaq_api import examples

    wanted = {name for e in examples.examples() for name in imported(e.text)}
    if failing(wanted):
        raise SystemExit(f"the examples import what is not here: {failing(wanted)}")
    named = [*script_modules.OURS, *script_modules.standard()]
    unavailable = {failed.split(":")[0] for failed in failing(named)}
    return sorted(wanted | (set(named) - unavailable))


def check(built: Optional[Path]) -> List[str]:
    """The modules the build's Python (or this one) cannot import."""
    from thzdaq_api.host import RUN_SCRIPT

    python = [str(built), RUN_SCRIPT] if built else [sys.executable]
    command = [*python, str(Path(__file__).resolve()), IMPORT, *expected()]
    done = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise SystemExit(f"{' '.join(python)} failed: {done.stderr[-2000:]}")
    return [line for line in done.stdout.splitlines() if line]


def main() -> int:
    if sys.argv[1:2] == [IMPORT]:
        print("\n".join(failing(sys.argv[2:])))
        return 0
    options = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    options.add_argument("built", nargs="?", type=Path, help="a build's thzdaq-cli")
    missing = check(options.parse_args().built)
    for line in missing:
        print(f"missing {line}", file=sys.stderr)
    print("scripts import what they need" if not missing else "")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
