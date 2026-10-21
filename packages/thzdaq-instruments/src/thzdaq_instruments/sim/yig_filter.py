from typing import Optional

from thzdaq_instruments.instrument import Channel, Instrument


class SimYigChannel(Channel):
    """YIG filter tuned by a DAC code: frequency = start + code * step."""

    instrument: "SimYigFilter"

    def __init__(self, instrument: "SimYigFilter", key: str):
        super().__init__(instrument, key)
        self.frequency = instrument.start_frequency

    def tune(self, frequency: float) -> float:
        code = round(
            (frequency - self.instrument.start_frequency) / self.instrument.step
        )
        return self.set_code(code)

    def set_code(self, code: int) -> float:
        code = min(max(code, 0), self.instrument.max_code)
        self.frequency = self.instrument.start_frequency + code * self.instrument.step
        return self.frequency


class SimYigFilter(Instrument):
    channel_class = SimYigChannel
    channel_keys = ("yig_1", "yig_2")

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        start_frequency: float = 2.97320263e9,  # Hz at code 0
        step: float = 2.46705639e6,  # Hz per code
        max_code: int = 4095,
    ):
        super().__init__(name=name)
        self.start_frequency = start_frequency
        self.step = step
        self.max_code = max_code

    def identify(self) -> str:
        return "THZDAQ,SimYigFilter,0,1.0"
