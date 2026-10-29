"""A lock the operating system holds for a process on a file: it goes when the
process ends, however it ends, so a crashed daemon leaves no stale lock."""

import sys
import time
from pathlib import Path
from typing import IO, Optional

# Taking a lock held by another process is retried this often until the timeout:
# the operating systems offer no timed wait on a file lock
RETRY_S = 0.05


class FileLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._file: Optional[IO] = None

    def acquire(self, timeout: float = 0.0) -> bool:
        """Take the lock, waiting up to timeout seconds; False if another holds it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = open(self.path, "a+b")
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock(file)
            except OSError:
                if time.monotonic() >= deadline:
                    file.close()
                    return False
                time.sleep(RETRY_S)
            else:
                self._file = file
                return True

    def release(self) -> None:
        if self._file is not None:
            _unlock(self._file)
            self._file.close()
            self._file = None

    @property
    def held(self) -> bool:
        return self._file is not None


if sys.platform == "win32":
    import msvcrt

    def _lock(file: IO) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(file: IO) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(file: IO) -> None:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(file: IO) -> None:
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)
