"""Coordinate atomic file replacement with readers, including on Windows."""

import hashlib
import os
import sys
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path

from thzdaq_api.lock import FileLock

ACCESS_S = 15.0


def _key(path: Path) -> str:
    """One name per file however the path is spelled, never beside the file:
    the folders of data stay as people left them."""
    where = os.path.normcase(str(path.parent.resolve() / path.name))
    return hashlib.sha256(where.encode("utf-8")).hexdigest()


def read_bytes(path: Path) -> bytes:
    # POSIX permits replacing an open file; Windows needs the same guard as
    # its writer. A named mutex lets readers use a read-only folder too.
    with file_access(path) if sys.platform == "win32" else nullcontext():
        return path.read_bytes()


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel.CreateMutexW.restype = wintypes.HANDLE
    _kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel.WaitForSingleObject.restype = wintypes.DWORD
    _kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _kernel.ReleaseMutex.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL

    @contextmanager
    def file_access(path: Path, timeout: float = ACCESS_S):
        """Serialize access across threads, processes and Windows sessions."""
        name = "Global\\ThzDAQ-file-" + _key(path)
        handle = _kernel.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            result = _kernel.WaitForSingleObject(handle, max(0, int(timeout * 1000)))
            if result == 0x102:
                raise TimeoutError(f"File access timed out: {path}")
            if result not in (0, 0x80):  # acquired, or abandoned by a dead owner
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                yield
            finally:
                if not _kernel.ReleaseMutex(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _kernel.CloseHandle(handle)

else:
    # This user's locks, as a named mutex is this machine's: a folder of /tmp
    # one user made the others could not write in
    LOCKS = Path(tempfile.gettempdir()) / f"thzdaq-locks-{os.getuid()}"

    @contextmanager
    def file_access(path: Path, timeout: float = ACCESS_S):
        """Serialize publishers; POSIX readers need no lock for replacement."""
        LOCKS.mkdir(parents=True, exist_ok=True)
        lock = FileLock(LOCKS / f"{_key(path)}.lock")
        if not lock.acquire(timeout):
            raise TimeoutError(f"File access timed out: {path}")
        try:
            yield
        finally:
            lock.release()
