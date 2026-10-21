from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelReading:
    """Measured output of a source or bias channel, SI units."""

    voltage: float  # V
    current: float  # A

    @property
    def power(self) -> float:
        """W"""
        return self.voltage * self.current
