"""The procedures on offer, by name: the built-in ones, listed explicitly."""

from typing import Dict, Iterable, List, Type

from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.measurements.procedures import BUILTIN


def by_name(procedures: Iterable[Type[Procedure]]) -> Dict[str, Type[Procedure]]:
    found: Dict[str, Type[Procedure]] = {}
    for cls in procedures:
        if not cls.name:
            raise ProcedureError(f"{cls.__name__} has no name")
        if cls.name in found:
            raise ProcedureError(f"Procedure {cls.name!r} is listed twice")
        found[cls.name] = cls
    return found


PROCEDURES = by_name(BUILTIN)


def get_procedure(name: str) -> Type[Procedure]:
    try:
        return PROCEDURES[name]
    except KeyError:
        raise ProcedureError(
            f"Unknown procedure {name!r}, available: {sorted(PROCEDURES)}"
        ) from None


def list_procedures() -> List[Type[Procedure]]:
    return [PROCEDURES[name] for name in sorted(PROCEDURES)]
