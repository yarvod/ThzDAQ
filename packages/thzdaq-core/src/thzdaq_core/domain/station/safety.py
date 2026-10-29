"""Safety of the bench: limits stricter than the passports of the instruments,
which protect the samples, and the safe state to return to (the profile's
safety section).

A guard puts both together for one device: what it accepts and how a change
goes, in steps no larger than ``step`` at no more than ``rate`` per second.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from thzdaq_instruments.errors import LimitError
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.quantities import Quantity


@dataclass(frozen=True)
class SafetyLimit(Limit):
    """Bench limits of one quantity of a device, in its SI unit: a value outside
    min..max is refused."""

    # A soft range inside min..max: beyond it a client is asked first
    warn_minimum: Optional[float] = None
    warn_maximum: Optional[float] = None
    step: Optional[
        float
    ] = None  # the largest change in one command: more goes in steps
    rate: Optional[float] = None  # units per second at most: a step waits step / rate

    def problems(self) -> List[str]:
        problems = []
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            problems.append("min is above max")
        for name, value in (
            ("warn_min", self.warn_minimum),
            ("warn_max", self.warn_maximum),
        ):
            if value is not None and self.problem(value):
                problems.append(f"{name} is outside min..max")
        for name, value in (("step", self.step), ("rate", self.rate)):
            if value is not None and value <= 0:
                problems.append(f"{name} must be positive")
        if self.rate is not None and self.step is None:
            problems.append("rate needs step")
        return problems


@dataclass
class Safety:
    """The profile's safety section, by device ref and quantity key."""

    limits: Dict[str, Dict[str, SafetyLimit]] = field(default_factory=dict)
    safe_state: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Supplies keep the voltage and current maxima themselves (OVP, OCP),
    # written when they are opened
    hardware_protection: bool = False

    def refs(self) -> List[str]:
        return list(dict.fromkeys([*self.limits, *self.safe_state]))

    def problems(self) -> List[str]:
        return [
            f"safety of {ref} {key}: {problem}"
            for ref, limits in self.limits.items()
            for key, limit in limits.items()
            for problem in limit.problems()
        ]


@dataclass(frozen=True)
class Guard:
    """What one device accepts, by quantity key: the passport of its driver and
    the bench limits; how a change goes."""

    device: str  # its ref, for messages
    passport: Mapping[str, Limit]
    bench: Mapping[str, SafetyLimit]

    def problem(self, quantity: Quantity, value: float) -> Optional[str]:
        """Why a value cannot be set, None when it can."""
        for source, limits in (("passport", self.passport), ("bench", self.bench)):
            limit = limits.get(quantity.key)
            wrong = limit.problem(value, quantity.unit) if limit else None
            if wrong:
                shown = f"{value:g} {quantity.unit}".strip()
                return f"{self.device} {quantity.key}: {shown} is {wrong} ({source})"
        return None

    def check(self, quantity: Quantity, value: float) -> None:
        problem = self.problem(quantity, value)
        if problem:
            raise LimitError(problem)

    def ramps(self, key: str) -> bool:
        limit = self.bench.get(key)
        return limit is not None and limit.step is not None

    def ladder(self, key: str, before: Optional[float], value: float) -> List[float]:
        """The values to write to go from before to value, the value last: equal
        steps no larger than the bench step."""
        limit = self.bench.get(key)
        if before is None or limit is None or limit.step is None:
            return [value]
        count = math.ceil(round(abs(value - before) / limit.step, 9))
        if count <= 1:
            return [value]
        return [before + (value - before) * i / count for i in range(1, count)] + [
            value
        ]

    def delay(self, key: str, change: float) -> float:
        """Seconds to wait after a step of this size, for the bench rate."""
        limit = self.bench.get(key)
        if limit is None or limit.rate is None:
            return 0.0
        return abs(change) / limit.rate
