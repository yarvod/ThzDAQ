"""The bench as a client sees it: operations called by their arguments.

RemoteLab calls the daemon; LocalLab (thzdaq-core) calls its use cases in the
same process. Both raise LabError when an operation fails.
"""

from typing import Protocol, TypeVar

from thzdaq_api.operation import Operation

R = TypeVar("R")


class Lab(Protocol):
    def call(self, operation: Operation[R]) -> R:
        ...
