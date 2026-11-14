from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    Union,
)

from thzdaq_api.leases import SHARED
from thzdaq_api.measurement_file import Column
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.parameters import Parameter, When
from thzdaq_api.measurements import PlotInfo

Capabilities = Union[Type, Tuple[Type, ...]]


class Procedure:
    """A measurement: declared parameters and device slots plus run(ctx).

    run() talks only to ctx: devices by slot, records, progress, cancellation.
    It never touches Qt, files or drivers, so it runs the same from the GUI,
    the CLI, a notebook or a test with simulators.
    """

    name: ClassVar[str] = ""  # registry key, e.g. "sis.current_vs_voltage"
    title: ClassVar[str] = ""
    description: ClassVar[str] = ""
    # How to measure with it, for agents and the assistant (describe_procedure):
    # what to do first, how a run goes, what to look at in the result
    guide: ClassVar[str] = ""
    # Device slots and the capabilities each needs, e.g. {"bias": VoltageSource}
    requires: ClassVar[Mapping[str, Capabilities]] = {}
    slot_titles: ClassVar[Mapping[str, str]] = {}
    # Preferred device kind per slot: lists show those first and only, when present
    slot_kinds: ClassVar[Mapping[str, str]] = {
        "bias": "sis_bias",
        "sis1": "sis_bias",
        "sis2": "sis_bias",
        "coil": "sis_coil",
        # A switch slot takes a supply channel, not any device with an output
        "if_selector": "channel",
    }
    # How a slot uses its device while the run lasts (thzdaq_api.leases): read,
    # exclusive (it sweeps the device) or, unlisted, shared
    slot_modes: ClassVar[Mapping[str, str]] = {}
    # Slots whose devices it leaves as it ends, setting them being what it is
    # for (demagnetization leaves the coil at the centre); every other device
    # it changes is set back as it ends
    leaves: ClassVar[Tuple[str, ...]] = ()
    plots: ClassVar[Tuple[PlotInfo, ...]] = ()
    # Parameters used only while another has some value (shown_while): a form
    # shows them then; those of mixins and subclasses add up
    shown_if: ClassVar[Mapping[str, When]] = {}
    # Record tables: titles, and columns whose title/unit differ from KNOWN_COLUMNS
    table_titles: ClassVar[Mapping[str, str]] = {}
    columns: ClassVar[Mapping[str, Column]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        reserved = {name for name in dir(Procedure) if not name.startswith("__")}
        clashes = sorted(
            key
            for key, value in vars(cls).items()
            if isinstance(value, Parameter) and key in reserved
        )
        if clashes:
            raise ProcedureError(
                f"{cls.__name__}: parameter names {clashes} clash with Procedure attributes"
            )
        parameters = cls.parameters()
        for name, conditions in cls.conditions().items():
            for condition in conditions:
                if {name, condition.parameter} - set(parameters):
                    raise ProcedureError(
                        f"{cls.__name__}: shown_if names {name!r} or "
                        f"{condition.parameter!r}, not its parameters"
                    )
                for value in condition.values:
                    parameters[condition.parameter].validate(value)

    def __init__(self, **values: Any):
        self._values: Dict[str, Any] = {}
        parameters = self.parameters()
        unknown = set(values) - set(parameters)
        if unknown:
            raise ProcedureError(f"{self.name}: unknown parameters {sorted(unknown)}")
        for key, value in values.items():
            setattr(self, key, value)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.values()})"

    @classmethod
    def parameters(cls) -> Dict[str, Parameter]:
        found: Dict[str, Parameter] = {}
        for klass in reversed(cls.__mro__):
            for key, value in vars(klass).items():
                if isinstance(value, Parameter):
                    found[key] = value
        return found

    @classmethod
    def conditions(cls) -> Dict[str, Tuple[When, ...]]:
        """What each parameter is used under (shown_if of the class and of
        those it is made of): all of them hold."""
        found: Dict[str, Tuple[When, ...]] = {}
        for klass in reversed(cls.__mro__):
            for name, condition in vars(klass).get("shown_if", {}).items():
                if condition not in found.get(name, ()):
                    found[name] = found.get(name, ()) + (condition,)
        return found

    def used(self, name: str) -> bool:
        """Whether a run uses the parameter, as the others stand (shown_if)."""
        return all(
            getattr(self, condition.parameter) in condition.values
            for condition in self.conditions().get(name, ())
        )

    @classmethod
    def from_json(
        cls, data: Mapping[str, Any], typed: Optional[Mapping[str, str]] = None
    ) -> "Procedure":
        """data as JSON carries it (SI); typed as people type it, in the units
        it is shown in ("0:7:351" for a sweep in mV). Raises ProcedureError
        naming every invalid parameter."""
        typed = typed or {}
        parameters = cls.parameters()
        unknown = (set(data) | set(typed)) - set(parameters)
        if unknown:
            raise ProcedureError(f"{cls.name}: unknown parameters {sorted(unknown)}")
        values, problems = {}, []
        given = [(key, value, False) for key, value in data.items()]
        given += [(key, text, True) for key, text in typed.items()]
        for key, value, as_typed in given:
            parameter = parameters[key]
            try:
                values[key] = (
                    parameter.parse(value) if as_typed else parameter.from_json(value)
                )
            except ProcedureError as e:
                problems.append(f"{parameter.label}: {e}")
        if problems:
            raise ProcedureError("; ".join(problems))
        return cls(**values)

    def values(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in self.parameters()}

    def to_json(self) -> Dict[str, Any]:
        return {
            key: parameter.to_json(getattr(self, key))
            for key, parameter in self.parameters().items()
        }

    def slots(self) -> Dict[str, Capabilities]:
        """Device slots this run needs; override when they depend on parameters."""
        return dict(self.requires)

    def slot_mode(self, slot: str) -> str:
        """read, shared or exclusive; override when it depends on parameters."""
        return self.slot_modes.get(slot, SHARED)

    @classmethod
    def slot_title(cls, slot: str) -> str:
        return cls.slot_titles.get(slot) or slot.replace("_", " ").capitalize()

    def check(self) -> List[str]:
        """Cross-parameter problems; override in procedures."""
        return []

    def planned(self) -> List[Tuple[str, str, Tuple[float, ...]]]:
        """(slot, quantity key, values) the run sets its devices to, as far as
        the parameters tell: the limits of the devices are checked before the
        run starts."""
        return [
            (*parameter.applies, parameter.bounds(getattr(self, key)))
            for key, parameter in self.parameters().items()
            if parameter.applies is not None and self.used(key)
        ]

    def validate(self) -> None:
        problems = []
        for key in self.parameters():
            try:
                getattr(self, key)
            except ProcedureError as e:
                problems.append(str(e))
        if not problems:
            problems.extend(self.check())
        if problems:
            raise ProcedureError(f"{self.name}: " + "; ".join(problems))

    def estimate_steps(self) -> Optional[int]:
        """Total steps for progress, None if unknown."""
        return None

    def active_plots(
        self, quantities: Optional[Callable[[str], Iterable[Any]]] = None
    ) -> Tuple[PlotInfo, ...]:
        """Plots this run fills, known before it starts (a viewer puts them on
        screen at Start); quantities(slot) lists what the device in a slot
        reads. Override when parameters or devices leave plots empty."""
        return self.plots

    def plot_window(self) -> Optional[float]:
        """Seconds of x the live graphs keep (a long monitor), None: everything."""
        return None

    def run(self, ctx) -> None:
        raise NotImplementedError
