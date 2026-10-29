"""How an operation fails: a code clients act on, a message people read, a hint."""

from enum import Enum

import msgspec


class ErrorCode(str, Enum):
    INVALID_ARGUMENTS = "invalid_arguments"  # the arguments do not fit the operation
    UNKNOWN_OPERATION = "unknown_operation"
    NOT_FOUND = "not_found"  # no such device, quantity, measurement
    NOT_ALLOWED = "not_allowed"  # the operation does not apply: a read-only value
    INSTRUMENT = "instrument"  # the instrument failed or did not answer
    # Outside the passport of the instrument or the bench limits: nothing was sent
    OUT_OF_LIMITS = "out_of_limits"
    CONFLICT = "conflict"  # a device in exclusive use: repeat with share to go on
    INTERNAL = "internal"  # a fault of the daemon: its log has the details
    UNREACHABLE = "unreachable"  # no daemon answers: not running, or gone
    UNAUTHORIZED = "unauthorized"  # the token is not this daemon's (a stale host file)
    WRONG_VERSION = "wrong_version"  # the daemon speaks another version of the contract


class Failure(msgspec.Struct, frozen=True):
    """A failed operation as it travels."""

    code: ErrorCode
    message: str
    hint: str = ""


class LabError(Exception):
    def __init__(self, code: ErrorCode, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def failure(self) -> Failure:
        return Failure(self.code, self.message, self.hint)

    @classmethod
    def from_failure(cls, failure: Failure) -> "LabError":
        return cls(failure.code, failure.message, failure.hint)

    def __str__(self) -> str:
        return f"{self.message} ({self.hint})" if self.hint else self.message
