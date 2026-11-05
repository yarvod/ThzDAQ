"""What every simulator does as an instrument."""

from typing import Optional

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Instrument

IDENTIFY = "*IDN?"  # the one raw command a simulator understands


class SimInstrument(Instrument):
    """A simulated instrument. It takes raw commands as a real one does, but
    understands only *IDN? (answered as identify() is): any other command is
    taken without effect, and asking it for an answer fails, since what the
    instrument would do is not simulated."""

    def identify(self) -> str:
        raise NotImplementedError

    def send_raw(self, command: str, answer: bool) -> Optional[str]:
        if command.strip().upper() == IDENTIFY:
            return self.identify()
        if answer:
            raise InstrumentResponseError(
                f"{self.name}: a simulator answers only {IDENTIFY}, not {command!r}"
            )
        return None
