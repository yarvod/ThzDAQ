"""Limits: the values a device accepts.

A driver declares the passport of its instrument, what it accepts at all, by
quantity key (``Instrument.limits``; ``channel_limits`` for channels that
differ). A value outside is refused before a command is sent: many instruments
silently clip it or set something of their own. Stricter limits that protect a
sample come from the bench profile.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Limit:
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    def problem(self, value: float, unit: str = "") -> Optional[str]:
        """What is wrong with a value ("above 30 V"), None when it is inside."""
        if self.minimum is not None and value < self.minimum:
            return f"below {self.minimum:g} {unit}".strip()
        if self.maximum is not None and value > self.maximum:
            return f"above {self.maximum:g} {unit}".strip()
        return None
