from typing import Dict, Optional

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import GENERIC
from thzdaq_instruments.sim.base import IDENTIFY, SimInstrument

QUERY = "?"


def header(command: str) -> str:
    """What a command is about, as SCPI compares it: "volt 2.5" and "VOLT?"
    are both about VOLT."""
    return command.replace(QUERY, " ").split(maxsplit=1)[0].upper()


class SimGenericScpi(SimInstrument):
    """An instrument without a driver, simulated: it remembers what was
    written ("VOLT 2.500" remembers 2.500 for VOLT) and answers a query
    ("VOLT?") with it. A query of what was never written fails, as nothing
    knows what the instrument would answer."""

    driver_key = "sim.generic_scpi"
    device_type = GENERIC

    def __init__(self, *, name: Optional[str] = None):
        super().__init__(name=name)
        self.written: Dict[str, str] = {}

    def identify(self) -> str:
        return "THZDAQ,SimGenericScpi,0,1.0"

    def send_raw(self, command: str, answer: bool) -> Optional[str]:
        command = command.strip()
        if not command:
            raise InstrumentResponseError(f"{self.name}: an empty command")
        if command.upper() == IDENTIFY:
            return self.identify()
        if QUERY in command:
            return self._answer(command)
        key, _, value = command.partition(" ")
        if value.strip():
            self.written[header(key)] = value.strip()
        return "" if answer else None

    def _answer(self, command: str) -> str:
        key = header(command)
        if key not in self.written:
            raise InstrumentResponseError(
                f"{self.name}: nothing was written to {key} yet; a simulator"
                f" answers {command!r} with what was"
            )
        return self.written[key]
