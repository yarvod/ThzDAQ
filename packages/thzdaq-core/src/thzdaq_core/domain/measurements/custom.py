"""The bench's own measurements as procedures: what a script declares at its
top (thzdaq_api.custom) makes the parameters, slots and plots of a procedure
custom.<its file name>. Values are declared as people type them, in their
unit: a parameter keeps that unit for display and the SI one inside.

A run of it is the script's process filling a session (thzdaq_core's
application.custom); the procedure itself describes the form and parses what
is given.
"""

from typing import Any, Dict, Tuple, Type

import msgspec
from thzdaq_api.custom import (
    BOOL,
    CHOICE,
    FLOAT,
    FLOAT_LIST,
    INT,
    SWEEP,
    TEXT,
    TEXT_LIST,
    Declarations,
    Given,
    ValueDeclared,
    procedure_name,
)
from thzdaq_api.measurement_file import column_for
from thzdaq_api.measurements import PlotInfo
from thzdaq_instruments.capabilities import ALL_CAPABILITIES
from thzdaq_instruments.units import unit_scale

from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.procedure import Capabilities, Procedure
from thzdaq_core.domain.parameters import (
    BoolParameter,
    ChoiceParameter,
    FloatListParameter,
    FloatParameter,
    IntParameter,
    Parameter,
    StringListParameter,
    SweepParameter,
    TextParameter,
)

CAPABILITIES = {c.__name__: c for c in ALL_CAPABILITIES}
SWEEP_PARTS = 3  # start:stop:points


def value_kind(declared: ValueDeclared) -> str:
    """The kind of a declared value, by its default (and choices)."""
    default = declared.default
    if declared.choices:
        return CHOICE
    if isinstance(default, bool):
        return BOOL
    if isinstance(default, int) and not declared.unit:
        return INT
    if isinstance(default, (int, float)):
        return FLOAT
    if isinstance(default, str):
        return SWEEP if len(default.split(":")) == SWEEP_PARTS else TEXT
    if isinstance(default, (list, tuple)) and default:
        numbers = all(isinstance(item, (int, float)) for item in default)
        return FLOAT_LIST if numbers else TEXT_LIST
    raise ProcedureError(
        f"{declared.name}: a value of {default!r}: give a number, true/false,"
        " a sweep 'start:stop:points', a text, a list or choices"
    )


def _typed(kind: str, default: Any) -> str:
    """A default as people type it."""
    if kind in (FLOAT_LIST, TEXT_LIST):
        return ", ".join(f"{item}" for item in default)
    return f"{default}"


def parameter(declared: ValueDeclared) -> Parameter:
    """The parameter of a declared value; its default parsed as typed.
    ProcedureError tells what is wrong with it."""
    kind = value_kind(declared)
    si, scale = unit_scale(declared.unit)
    scaled = {
        "unit": si,
        "display_unit": declared.unit,
        "display_scale": scale,
        "help": declared.help,
    }
    bounds = {
        "minimum": None if declared.minimum is None else declared.minimum * scale,
        "maximum": None if declared.maximum is None else declared.maximum * scale,
    }
    made: Dict[str, Parameter] = {
        FLOAT: FloatParameter(declared.title, **bounds, **scaled),
        INT: IntParameter(declared.title, **bounds, help=declared.help),
        BOOL: BoolParameter(declared.title, help=declared.help),
        SWEEP: SweepParameter(declared.title, **scaled),
        TEXT: TextParameter(declared.title, help=declared.help),
        FLOAT_LIST: FloatListParameter(declared.title, **scaled),
        TEXT_LIST: StringListParameter(declared.title, help=declared.help),
    }
    found = (
        ChoiceParameter(declared.title, declared.choices, help=declared.help)
        if kind == CHOICE
        else made[kind]
    )
    found.name = declared.name
    try:
        found.default = (
            found.validate(declared.default)
            if kind in (BOOL, TEXT)
            else found.parse(_typed(kind, declared.default))
        )
    except ProcedureError as e:
        raise ProcedureError(f"{declared.name}: {e}") from None
    return found


def given(found: Parameter, value: Any) -> Given:
    """A value of a parameter as a script is given it."""
    return Given(found.to_json(value), found.unit, found.kind)


def needs(capabilities: Tuple[str, ...]) -> Capabilities:
    """The capabilities a slot names, as classes; any device for none."""
    unknown = [name for name in capabilities if name not in CAPABILITIES]
    if unknown:
        raise ProcedureError(
            f"No capability {', '.join(unknown)}: one of {', '.join(CAPABILITIES)}"
        )
    return tuple(CAPABILITIES[name] for name in capabilities) or object


def plot_key(procedure: str, name: str) -> str:
    """custom.pv_hot_cold, pv -> custom.pv_hot_cold.pv"""
    return f"{procedure}.{name}"


class CustomProcedure(Procedure):
    """A procedure a script declares; its run is the script's (see
    application.custom), so run() is never called on it."""

    declarations: Declarations = Declarations()

    def given(self) -> Dict[str, Given]:
        """Its values as the script is given them."""
        return {
            key: given(found, getattr(self, key))
            for key, found in self.parameters().items()
        }

    def run(self, ctx) -> None:
        raise ProcedureError(f"{self.name} runs as its script's process")


def custom_procedure(
    name: str, title: str, description: str, declarations: Declarations
) -> Type[CustomProcedure]:
    """The procedure custom.<name> of a script's declarations;
    ProcedureError for declarations it cannot be made of."""
    named = procedure_name(name)
    attributes: Dict[str, Any] = {
        value.name: parameter(value) for value in declarations.values
    }
    attributes.update(
        name=named,
        title=title,
        description=description,
        declarations=declarations,
        requires={slot.name: needs(slot.capabilities) for slot in declarations.slots},
        slot_titles={slot.name: slot.title for slot in declarations.slots},
        slot_kinds={slot.name: slot.kind for slot in declarations.slots if slot.kind},
        plots=tuple(drawn(named, plot) for plot in declarations.plots),
    )
    return type(f"Custom_{name}", (CustomProcedure,), attributes)


def drawn(procedure: str, plot: PlotInfo) -> PlotInfo:
    """A declared plot as the procedure fills it: its key, and labels of its
    axes from the columns known by their keys."""
    x, y = column_for(plot.x), column_for(plot.y)
    return msgspec.structs.replace(
        plot,
        key=plot_key(procedure, plot.key),
        x_label=plot.x_label or x.label,
        y_label=plot.y_label or y.label,
    )
