"""The bench's library of its own measurements (the Library port): the Python
scripts of a folder, measurements/ of the program's. A script is described
by running it with DESCRIBE_ENV: its declarations go to a file, and connect()
ends it before it touches the bench (thzdaq_api.custom).
"""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Sequence, Tuple

import msgspec
from thzdaq_api.custom import DESCRIBE_ENV, INPUTS_ENV, SUFFIX, Declarations
from thzdaq_api.host import apart, script_python

from thzdaq_core.application.ports import DescribeFailed, LibraryFile

DESCRIBE_S = 15.0  # a script describes itself within this, or is ended
TOLD = 4000  # characters of what a failed description printed, at most
SKIPPED = ("_", ".")  # files that are no measurements: helpers, hidden ones
DECLARED = "declared.json"


def told(text: str) -> str:
    """The end of what a process printed: its traceback."""
    return text[-TOLD:].strip()


class FolderLibrary:
    def __init__(
        self,
        folder: Path,
        python: Callable[[], Sequence[str]] = script_python,
        timeout: float = DESCRIBE_S,
    ):
        """python: how a script is run (this program's Python)."""
        self.folder = Path(folder)
        self.python = python
        self.timeout = timeout

    def files(self) -> Tuple[LibraryFile, ...]:
        if not self.folder.is_dir():
            return ()
        found = []
        for path in sorted(self.folder.glob(f"*{SUFFIX}")):
            if path.name.startswith(SKIPPED) or not path.is_file():
                continue
            data = path.read_bytes()
            found.append(
                LibraryFile(
                    path.stem,
                    str(path),
                    data.decode("utf-8", errors="replace"),
                    hashlib.sha256(data).hexdigest(),
                )
            )
        return tuple(found)

    def describe(self, file: LibraryFile) -> Declarations:
        with tempfile.TemporaryDirectory() as folder:
            declared = Path(folder) / DECLARED
            environment = {
                key: value for key, value in os.environ.items() if key != INPUTS_ENV
            }
            environment[DESCRIBE_ENV] = str(declared)
            try:
                done = subprocess.run(
                    [*self.python(), file.path],
                    cwd=self.folder,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=self.timeout,
                    **apart(),
                )
            except subprocess.TimeoutExpired:
                raise DescribeFailed(
                    f"not described in {self.timeout:g} s: declarations come"
                    " first, before anything that takes long"
                ) from None
            except OSError as e:
                raise DescribeFailed(f"{self.python()[0]} did not start: {e}") from None
            output = (done.stdout + done.stderr).decode("utf-8", errors="replace")
            if done.returncode != 0:
                raise DescribeFailed(told(output) or f"exit code {done.returncode}")
            if not declared.exists():
                return Declarations()
            try:
                return msgspec.json.decode(declared.read_bytes(), type=Declarations)
            except msgspec.DecodeError as e:
                raise DescribeFailed(f"its declarations are not read: {e}") from None
