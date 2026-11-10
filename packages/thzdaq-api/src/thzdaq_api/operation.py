"""An operation of the bench: a Struct of its arguments whose class says what it is.

The class name gives the operation's name (SetQuantity -> set_quantity), its
docstring tells people and models what it does (it becomes the description in
the JSON schema), the generic parameter is the type of the result, and two
class variables classify it: the rights it needs and whether it takes long.
"""

import re
import typing
from enum import Enum
from typing import ClassVar, Generic, TypeVar

import msgspec

R = TypeVar("R")


class Rights(str, Enum):
    """What an operation may change; agents and scripts get rights by these."""

    READ = "read"  # looks, changes nothing
    SET = "set"  # changes a device
    RUN = "run"  # starts measurements, notes on them
    STOP = "stop"  # ends measurements, brings devices to their safe state
    STATION = "station"  # changes the profile, or what agents may do
    DAEMON = "daemon"  # stops or restarts the daemon
    ANSWER = "answer"  # answers for a person what waits for one
    RAW_QUERY = "raw_query"  # asks an instrument a raw command (with ?)
    RAW_WRITE = "raw_write"  # sends an instrument a raw command nothing checks
    LIBRARY = "library"  # writes the bench's own measurements (measurements/)


class Operation(
    msgspec.Struct, Generic[R], kw_only=True, frozen=True, forbid_unknown_fields=True
):
    # Arguments cannot be called name, rights or long: these describe the class
    name: ClassVar[str] = ""
    rights: ClassVar[Rights] = Rights.READ
    long: ClassVar[bool] = False  # may take minutes: started, then waited for apart

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "name" not in vars(cls):
            cls.name = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()

    @classmethod
    def result_type(cls) -> type:
        for base in getattr(cls, "__orig_bases__", ()):
            if typing.get_origin(base) is Operation:
                return typing.get_args(base)[0]
        raise TypeError(f"{cls.__name__} does not say what it returns")
