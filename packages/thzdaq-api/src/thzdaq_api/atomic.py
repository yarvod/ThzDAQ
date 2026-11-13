"""Coordinate atomic file replacement with readers, including on Windows."""

import os
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path

from thzdaq_api.lock import FileLock

ACCESS_S = 15.0


def read_bytes(path: Path) -> bytes:
    # POSIX permits replacing an open file; Windows needs the same guard as
    # its writer. A named mutex lets readers use a read-only folder too.
    with file_access(path) if sys.platform == "win32" else nullcontext():
        return path.read_bytes()


if sys.platform == "win32":
    import ctypes
    import hashlib
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
        key = os.path.normcase(str(path.parent.resolve() / path.name))
        name = "Global\\ThzDAQ-file-" + hashlib.sha256(key.encode("utf-8")).hexdigest()
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

    @contextmanager
    def file_access(path: Path, timeout: float = ACCESS_S):
        """Serialize publishers; POSIX readers need no lock for replacement."""
        lock = FileLock(path.with_name(path.name + ".lock"))
        if not lock.acquire(timeout):
            raise TimeoutError(f"File access timed out: {path}")
        try:
            yield
        finally:
            lock.release()
