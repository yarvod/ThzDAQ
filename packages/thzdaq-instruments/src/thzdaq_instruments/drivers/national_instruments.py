from typing import Optional, Tuple

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import Channel, Instrument
from thzdaq_instruments.transport.base import HTTP, ConnectionSpec
from thzdaq_instruments.transport.http import JsonClient, JsonHttpClient

# Linear calibration of the digital YIG driver: frequency = a * code + b
DEFAULT_CODE_TO_FREQUENCY = (2.46705639e06, 2.97320263e09)


class YigChannel(Channel):
    """One YIG filter on the NI DAQ: TunableFilter."""

    instrument: "NiYigFilter"

    def __init__(self, instrument: "NiYigFilter", key: str):
        super().__init__(instrument, key)
        self.frequency: Optional[float] = None

    def tune(self, frequency: float) -> float:
        return self.set_code(self.instrument.frequency_to_code(frequency))

    def set_code(self, code: int) -> float:
        """Write the raw DAC code, returns the resulting frequency, Hz."""
        self.frequency = self.instrument._write_code(self.key, code)
        return self.frequency


class NiYigFilter(Instrument):
    """Digital YIG filters driven by the NI DAQ REST service."""

    channel_class = YigChannel
    channel_keys = ("yig_1", "yig_2")

    def __init__(
        self,
        connection: Optional[ConnectionSpec] = None,
        *,
        name: Optional[str] = None,
        device: str = "Dev1",
        code_to_frequency: Tuple[float, float] = DEFAULT_CODE_TO_FREQUENCY,
        client: Optional[JsonClient] = None,
    ):
        super().__init__(name=name)
        if client is None:
            client = JsonHttpClient(connection or self.connection())
        self.client = client
        self.device = device
        self.slope, self.intercept = code_to_frequency

    @staticmethod
    def connection(host: str = "169.254.0.86", timeout: float = 5.0) -> ConnectionSpec:
        return ConnectionSpec(HTTP, host=host, timeout=timeout)

    def frequency_to_code(self, frequency: float) -> int:
        return round((frequency - self.intercept) / self.slope)

    def code_to_frequency(self, code: int) -> float:
        return self.slope * code + self.intercept

    def _write_code(self, yig: str, code: int) -> float:
        response = self.client.post(
            f"/devices/{self.device}/write/{yig}/", {"value": int(code)}
        )
        result = response.get("result")
        if result is None:
            raise InstrumentResponseError(f"{self.name}: no result in {response!r}")
        return self.code_to_frequency(int(result))

    def identify(self) -> str:
        return f"NI YIG {self.device} {self.name}"

    def test(self) -> bool:
        self.client.get("/")
        return True

    def devices(self):
        return self.client.get("/devices/")

    def start(self) -> None:
        self.client.post(f"/devices/{self.device}/start")

    def stop(self) -> None:
        self.client.post(f"/devices/{self.device}/stop")

    def reset(self) -> None:
        self.client.post(f"/devices/{self.device}/reset")

    def close(self) -> None:
        self.client.close()
