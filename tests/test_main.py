"""main.py is the program and, with --serve, the daemon its clients start."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_serve_runs_the_daemon():
    done = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--serve", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0 and "ThzDAQ bench daemon" in done.stdout
