"""The bench's library of its own measurements (the Library port): the Python
scripts of a folder, measurements/ of the program's. A script's text is
described by running it with DESCRIBE_ENV: its declarations go to a file,
and it ends after the last one, before it touches the bench
(thzdaq_api.custom). The text runs from a hidden copy next to the scripts:
it imports what they import, and a text not saved yet is described alike.
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
            found.append(self._file(path, data))
        return tuple(found)

    @staticmethod
    def _file(path: Path, data: bytes) -> LibraryFile:
        return LibraryFile(
            path.stem,
            str(path),
            data.decode("utf-8", errors="replace"),
            hashlib.sha256(data).hexdigest(),
        )

    def file(self, name: str, text: str) -> LibraryFile:
        return self._file(self.folder / f"{name}{SUFFIX}", text.encode("utf-8"))

    def write(self, name: str, text: str) -> LibraryFile:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{name}{SUFFIX}"
        data = text.encode("utf-8")
        path.write_bytes(data)
        return self._file(path, data)

    def describe(self, file: LibraryFile) -> Declarations:
        self.folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=self.folder,
            prefix=f".{file.name}.", suffix=SUFFIX, delete=False,
        ) as copy:  # fmt: skip
            copy.write(file.text)
        try:
            return self._described(Path(copy.name))
        finally:
            Path(copy.name).unlink(missing_ok=True)

    def _described(self, copy: Path) -> Declarations:
        with tempfile.TemporaryDirectory() as folder:
            declared = Path(folder) / DECLARED
            environment = {
                key: value for key, value in os.environ.items() if key != INPUTS_ENV
            }
            environment[DESCRIBE_ENV] = str(declared)
            try:
                done = subprocess.run(
                    [*self.python(), str(copy)],
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
