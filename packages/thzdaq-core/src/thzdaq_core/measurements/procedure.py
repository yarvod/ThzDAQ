from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple, Type, Union

from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.parameters import Parameter
from thzdaq_core.measurements.plots import PlotSpec

Capabilities = Union[Type, Tuple[Type, ...]]


class Procedure:
    """A measurement: declared parameters and roles plus run(ctx).

    run() talks only to ctx: ports by role, records, progress, cancellation.
    It never touches Qt, files or drivers, so it runs the same from the GUI,
    the CLI, a notebook or a test with simulators.
    """

    name: ClassVar[str] = ""  # registry key, e.g. "sis.iv_curve"
    title: ClassVar[str] = ""
    description: ClassVar[str] = ""
    requires: ClassVar[Mapping[str, Capabilities]] = {}
    plots: ClassVar[Tuple[PlotSpec, ...]] = ()

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
