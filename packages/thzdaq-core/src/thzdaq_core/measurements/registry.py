from typing import Dict, List, Type

from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.procedure import Procedure

PROCEDURES: Dict[str, Type[Procedure]] = {}


def register_procedure(cls: Type[Procedure]) -> Type[Procedure]:
    """Class decorator: makes a procedure available to the CLI and GUI by its name."""
    if not cls.name:
        raise ProcedureError(f"{cls.__name__} has no name")
    existing = PROCEDURES.get(cls.name)
    if existing is not None and existing is not cls:
        raise ProcedureError(f"Procedure {cls.name!r} is already registered")
    PROCEDURES[cls.name] = cls
    return cls


def _load_builtin() -> None:
    import thzdaq_core.measurements.procedures  # noqa: F401  registers on import


def get_procedure(name: str) -> Type[Procedure]:
    _load_builtin()
    try:
        return PROCEDURES[name]
    except KeyError:
        raise ProcedureError(
            f"Unknown procedure {name!r}, available: {sorted(PROCEDURES)}"
        ) from None


def list_procedures() -> List[Type[Procedure]]:
    _load_builtin()
    return [PROCEDURES[name] for name in sorted(PROCEDURES)]
