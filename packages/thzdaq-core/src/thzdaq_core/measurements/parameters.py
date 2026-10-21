"""Declarative procedure parameters (PyMeasure-style).

Values live in SI inside procedures. Each parameter also knows its display unit
and scale, so forms, CLI and saved metadata talk in GHz / mV while the code
stays in Hz / V.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from thzdaq_instruments.readings import linspace

from thzdaq_core.errors import ProcedureError

MISSING: Any = object()


@dataclass(frozen=True)
class Sweep:
    """Inclusive linear sweep, SI units."""

    start: float
    stop: float
    points: int

    def values(self) -> List[float]:
        return linspace(self.start, self.stop, self.points)

    def __len__(self) -> int:
        return self.points

    @property
    def step(self) -> float:
        return 0.0 if self.points < 2 else (self.stop - self.start) / (self.points - 1)


class Parameter:
    kind = "value"

    def __init__(
        self,
        label: str,
        *,
        default: Any = MISSING,
        unit: str = "",
        display_unit: Optional[str] = None,
        display_scale: float = 1.0,
        help: str = "",
    ):
        self.label = label
        self.unit = unit  # SI unit of the value
        self.display_unit = display_unit if display_unit is not None else unit
        self.display_scale = display_scale  # SI value / display_scale = shown value
        self.help = help
        self.name = ""
        self.default = MISSING if default is MISSING else self.validate(default)

    def __set_name__(self, owner, name: str) -> None:
        self.name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        if self.name in instance._values:
            return instance._values[self.name]
        if self.default is MISSING:
            raise ProcedureError(f"Parameter {self.name!r} is required")
        return self.default

    def __set__(self, instance, value) -> None:
        try:
            instance._values[self.name] = self.validate(value)
        except ProcedureError as e:
            raise ProcedureError(f"{self.name}: {e}") from None

    def validate(self, value: Any) -> Any:
        return value

    def parse(self, text: str) -> Any:
        """Value typed by a user, in display units."""
        return self.validate(text)

    def to_json(self, value: Any) -> Any:
        return value

    def from_json(self, data: Any) -> Any:
        return self.validate(data)

    def format(self, value: Any) -> str:
        return f"{value}"

    def describe(self) -> Dict[str, Any]:
        default = None if self.default is MISSING else self.to_json(self.default)
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "unit": self.unit,
            "display_unit": self.display_unit,
            "display_scale": self.display_scale,
            "default": default,
            "required": self.default is MISSING,
            "help": self.help,
        }


def _number(value: Any, cast=float):
    if isinstance(value, bool):
        raise ProcedureError(f"expected a number, got {value!r}")
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ProcedureError(f"expected a number, got {value!r}") from None


class FloatParameter(Parameter):
    kind = "float"

    def __init__(
        self,
        label: str,
        *,
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
        **kwargs,
    ):
        self.minimum = minimum
        self.maximum = maximum
        super().__init__(label, **kwargs)

    def validate(self, value: Any) -> float:
        value = _number(value)
        if self.minimum is not None and value < self.minimum:
            raise ProcedureError(f"{value} is below {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ProcedureError(f"{value} is above {self.maximum}")
        return value

    def parse(self, text: str) -> float:
        return self.validate(_number(text) * self.display_scale)

    def format(self, value: float) -> str:
        return f"{value / self.display_scale:g} {self.display_unit}".strip()

    def describe(self) -> Dict[str, Any]:
        return {**super().describe(), "minimum": self.minimum, "maximum": self.maximum}


class IntParameter(FloatParameter):
    kind = "int"

    def validate(self, value: Any) -> int:
        number = _number(value)
        if number != int(number):
            raise ProcedureError(f"expected an integer, got {value!r}")
        return int(super().validate(int(number)))

    def parse(self, text: str) -> int:
        return self.validate(_number(text))

    def format(self, value: int) -> str:
        return f"{value} {self.display_unit}".strip()


class BoolParameter(Parameter):
    kind = "bool"

    def validate(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        raise ProcedureError(f"expected true/false, got {value!r}")

    def parse(self, text: str) -> bool:
        lowered = str(text).strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ProcedureError(f"expected true/false, got {text!r}")


class ChoiceParameter(Parameter):
    kind = "choice"

    def __init__(self, label: str, choices: Sequence[Any], **kwargs):
        if not choices:
            raise ProcedureError("ChoiceParameter needs choices")
        self.choices = tuple(choices)
        super().__init__(label, **kwargs)

    def validate(self, value: Any) -> Any:
        if value not in self.choices:
            raise ProcedureError(f"{value!r} is not one of {self.choices}")
        return value

    def parse(self, text: str) -> Any:
        for choice in self.choices:
            if str(choice) == str(text).strip():
                return choice
        return self.validate(text)

    def describe(self) -> Dict[str, Any]:
        return {**super().describe(), "choices": list(self.choices)}


class FloatListParameter(Parameter):
    kind = "float_list"

    def validate(self, value: Any) -> Tuple[float, ...]:
        if isinstance(value, (str, bytes)) or not hasattr(value, "__iter__"):
            raise ProcedureError(f"expected a list of numbers, got {value!r}")
        values = tuple(_number(v) for v in value)
        if not values:
            raise ProcedureError("list is empty")
        return values

    def parse(self, text: str) -> Tuple[float, ...]:
        items = [item for item in re.split(r"[,;\s]+", str(text).strip()) if item]
        return self.validate([_number(item) * self.display_scale for item in items])

    def to_json(self, value) -> List[float]:
        return list(value)

    def format(self, value) -> str:
        shown = ", ".join(f"{v / self.display_scale:g}" for v in value)
        return f"{shown} {self.display_unit}".strip()


class StringListParameter(Parameter):
    """Free list of names, e.g. station roles to monitor."""

    kind = "string_list"

    def validate(self, value: Any) -> Tuple[str, ...]:
        if isinstance(value, str) or not hasattr(value, "__iter__"):
            raise ProcedureError(f"expected a list of names, got {value!r}")
        values = tuple(str(v).strip() for v in value if str(v).strip())
        if not values:
            raise ProcedureError("list is empty")
        return values

    def parse(self, text: str) -> Tuple[str, ...]:
        return self.validate(re.split(r"[,;\s]+", str(text).strip()))

    def to_json(self, value) -> List[str]:
        return list(value)

    def format(self, value) -> str:
        return ", ".join(value)


class MultiChoiceParameter(Parameter):
    """Several of the choices, in the given order: e.g. S-parameters to measure."""

    kind = "multi_choice"

    def __init__(self, label: str, choices: Sequence[Any], **kwargs):
        if not choices:
            raise ProcedureError("MultiChoiceParameter needs choices")
        self.choices = tuple(choices)
        super().__init__(label, **kwargs)

    def validate(self, value: Any) -> Tuple[Any, ...]:
        if isinstance(value, str) or not hasattr(value, "__iter__"):
            raise ProcedureError(f"expected a list of choices, got {value!r}")
        values = tuple(value)
        if not values:
            raise ProcedureError("select at least one")
        wrong = [v for v in values if v not in self.choices]
        if wrong:
            raise ProcedureError(f"{wrong} not in {self.choices}")
        return values

    def parse(self, text: str) -> Tuple[Any, ...]:
        return self.validate(
            [item for item in re.split(r"[,;\s]+", str(text).strip()) if item]
        )

    def to_json(self, value) -> List[Any]:
        return list(value)

    def format(self, value) -> str:
        return ", ".join(map(str, value))

    def describe(self) -> Dict[str, Any]:
        return {**super().describe(), "choices": list(self.choices)}


class SweepParameter(Parameter):
    kind = "sweep"

    def __init__(self, label: str, *, max_points: int = 100001, **kwargs):
        self.max_points = max_points
        super().__init__(label, **kwargs)

    def validate(self, value: Any) -> Sweep:
        if isinstance(value, Sweep):
            sweep = value
        elif isinstance(value, dict):
            sweep = Sweep(
                _number(value.get("start")),
                _number(value.get("stop")),
                _number(value.get("points"), int),
            )
        elif isinstance(value, (tuple, list)) and len(value) == 3:
            sweep = Sweep(_number(value[0]), _number(value[1]), _number(value[2], int))
        else:
            raise ProcedureError(f"expected (start, stop, points), got {value!r}")
        if not 1 <= sweep.points <= self.max_points:
            raise ProcedureError(f"points must be 1..{self.max_points}")
        return sweep

    def parse(self, text: str) -> Sweep:
        """'start:stop:points' in display units, e.g. '4:12:201'"""
        parts = str(text).split(":")
        if len(parts) != 3:
            raise ProcedureError(f"expected start:stop:points, got {text!r}")
        scale = self.display_scale
        return self.validate(
            (
                _number(parts[0]) * scale,
                _number(parts[1]) * scale,
                _number(parts[2], int),
            )
        )

    def to_json(self, value: Sweep) -> Dict[str, Any]:
        return {"start": value.start, "stop": value.stop, "points": value.points}

    def format(self, value: Sweep) -> str:
        scale = self.display_scale
        return (
            f"{value.start / scale:g}..{value.stop / scale:g} {self.display_unit}, "
            f"{value.points} points"
        )
