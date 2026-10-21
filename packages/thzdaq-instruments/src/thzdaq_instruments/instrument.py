from typing import Any, ClassVar, Dict, Hashable, Optional, Tuple, Type

from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.transport.base import Transport


class Channel:
    """Addressable part of an instrument: supply output, SIS bias device, ..."""

    def __init__(self, instrument: "Instrument", key: Hashable):
        self.instrument = instrument
        self.key = key

    @property
    def name(self) -> str:
        return f"{self.instrument.name}/{self.key}"

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name!r})"


class Instrument:
    """Base of every driver and simulator: name, channels, lifecycle."""

    channel_class: ClassVar[Optional[Type[Channel]]] = None
    channel_keys: ClassVar[Tuple[Hashable, ...]] = ()

    def __init__(self, *, name: Optional[str] = None):
        self.name = name or self.__class__.__name__
        self._channels: Dict[Hashable, Channel] = {}

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name!r})"

    def channel(self, key: Hashable) -> Channel:
        if self.channel_class is None:
            raise ConfigurationError(f"{self.name} has no channels")
        if self.channel_keys and key not in self.channel_keys:
            raise ConfigurationError(
                f"{self.name} has no channel {key!r}, available: {self.channel_keys}"
            )
        if key not in self._channels:
            self._channels[key] = self.channel_class(self, key)
        return self._channels[key]

    @property
    def channels(self) -> Tuple[Channel, ...]:
        return tuple(self.channel(key) for key in self.channel_keys)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


class ScpiInstrument(Instrument):
    """Message based instrument: text commands over a Transport."""

    def __init__(self, transport: Transport, *, name: Optional[str] = None):
        super().__init__(name=name)
        self.transport = transport

    def write(self, command: str) -> None:
        self.transport.write(command)

    def query(self, command: str) -> str:
        return self.transport.query(command).strip()

    def _parse(self, command: str, response: str, parser) -> Any:
        try:
            return parser(response)
        except (TypeError, ValueError) as e:
            raise InstrumentResponseError(
                f"{self.name}: unexpected answer {response!r} to {command!r}"
            ) from e

    def query_float(self, command: str) -> float:
        return self._parse(command, self.query(command), float)

    def query_int(self, command: str) -> int:
        return self._parse(command, self.query(command), lambda r: int(float(r)))

    def query_bool(self, command: str) -> bool:
        def parse(response: str) -> bool:
            value = response.upper()
            if value in ("1", "ON"):
                return True
            if value in ("0", "OFF"):
                return False
            raise ValueError(response)

        return self._parse(command, self.query(command), parse)

    def identify(self) -> str:
        return self.query("*IDN?")

    def close(self) -> None:
        self.transport.close()
