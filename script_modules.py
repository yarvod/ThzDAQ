"""What scripts import from a build's own Python (thzdaq-cli run-script: the
bench's own measurements, scripts the window runs, a console's kernel).
PyInstaller takes in only the modules it finds imported, so ThzDAQ.spec names
these to the command line's analysis, and check_scripts.py imports them with
a build: ours with every module of theirs, numpy through them, and the whole
standard library but for what a script at the bench has no use for.
"""

import sys
from typing import List

OURS = ("thzdaq", "thzdaq_analysis")
# Tk windows and IDLE, Python's own tests, tools that make environments, and
# modules that only print or open a browser
LEFT_OUT = frozenset(
    (
        "antigravity", "this", "tkinter", "turtle", "turtledemo", "idlelib",
        "test", "lib2to3", "ensurepip", "venv", "pydoc_data", "distutils",
    )
)  # fmt: skip


def standard() -> List[str]:
    """The public top-level modules of the standard library a script may
    import, those of other systems too (absent here, they are not taken)."""
    return sorted(
        name
        for name in sys.stdlib_module_names
        if not name.startswith("_") and name not in LEFT_OUT
    )


def a_test(name: str) -> bool:
    """unittest.test, ctypes.test, ...: the tests a package of the standard
    library carries."""
    return any(part in ("test", "tests") for part in name.split("."))
