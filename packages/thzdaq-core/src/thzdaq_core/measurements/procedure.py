from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple, Type, Union

from thzdaq_core.data.measurement import Column
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.parameters import Parameter
from thzdaq_core.measurements.plots import PlotSpec

Capabilities = Union[Type, Tuple[Type, ...]]


class Procedure:
    """A measurement: declared parameters and device slots plus run(ctx).

    run() talks only to ctx: devices by slot, records, progress, cancellation.
    It never touches Qt, files or drivers, so it runs the same from the GUI,
    the CLI, a notebook or a test with simulators.
    """

    name: ClassVar[str] = ""  # registry key, e.g. "sis.iv_curve"
    title: ClassVar[str] = ""
    description: ClassVar[str] = ""
    # Device slots and the capabilities each needs, e.g. {"bias": VoltageSource}
    requires: ClassVar[Mapping[str, Capabilities]] = {}
    slot_titles: ClassVar[Mapping[str, str]] = {}
    # Preferred device kind per slot: lists show those first and only, when present
    slot_kinds: ClassVar[Mapping[str, str]] = {
        "bias": "sis_bias",
        "sis1": "sis_bias",
        "sis2": "sis_bias",
        "coil": "sis_coil",
    }
    plots: ClassVar[Tuple[PlotSpec, ...]] = ()
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
    def from_json(cls, data: Mapping[str, Any]) -> "Procedure":
        parameters = cls.parameters()
        unknown = set(data) - set(parameters)
        if unknown:
            raise ProcedureError(f"{cls.name}: unknown parameters {sorted(unknown)}")
        return cls(
            **{key: parameters[key].from_json(value) for key, value in data.items()}
        )

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

    @classmethod
    def slot_title(cls, slot: str) -> str:
        return cls.slot_titles.get(slot) or slot.replace("_", " ").capitalize()

    def check(self) -> List[str]:
        """Cross-parameter problems; override in procedures."""
        return []

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

    def run(self, ctx) -> None:
        raise NotImplementedError
