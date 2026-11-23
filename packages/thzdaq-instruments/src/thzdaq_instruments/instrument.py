from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Hashable,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
)

from thzdaq_instruments.capabilities import Identifiable, RawCommands
from thzdaq_instruments.errors import ConfigurationError, InstrumentResponseError
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.transport.base import (
    ConnectionSpec,
    Transport,
    connection_fields,
)

# The device type of an instrument without a driver of its own: it takes raw
# commands only (drivers/generic.py)
GENERIC = "generic"

# SYST:ERR? answers read at most, should a queue never say it is empty
ERROR_QUEUE_READS = 32


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


@dataclass(frozen=True)
class SubdeviceType:
    """A functional device the instrument hosts, added by the user.

    Unlike fixed channels (supply outputs), sub-devices are configured: which
    DEV of a SIS block is a bias and which a coil depends on the bench.
    """

    title: str
    accessor: str = "channel"  # instrument method returning the part for a key
    keys: Tuple[Hashable, ...] = ()
    part_class: Optional[type] = None  # what the accessor returns, for capabilities


class Instrument:
    """Base of every driver and simulator: name, channels, lifecycle.

    channel_keys are physical channels fixed by the model (supply outputs);
    subdevices are the kinds of functional devices a user adds (SIS bias,
    coil, heater output).
    """

    driver_key: ClassVar[str] = ""  # its id in profiles and the registry: rigol.dp832a
    device_type: ClassVar[str] = ""  # the kind of device it is: power_supply
    channel_class: ClassVar[Optional[Type[Channel]]] = None
    channel_keys: ClassVar[Tuple[Hashable, ...]] = ()
    subdevices: ClassVar[Dict[str, SubdeviceType]] = {}
    # The passport: what the instrument accepts at all, by quantity key, of
    # itself or of every channel; channel_limits for channels that differ
    limits: ClassVar[Mapping[str, Limit]] = {}
    channel_limits: ClassVar[Mapping[Hashable, Mapping[str, Limit]]] = {}
    # It keeps its configuration (its persistent quantities) itself, set on its
    # panel and kept over a power cycle: the profile's settings are not written
    # to it as it opens. False: the program keeps it, and the station writes
    # them on every open (a simulator, a sensor that forgets all when unplugged)
    keeps_settings: ClassVar[bool] = True
    # How the driver is connected: a static connection(...) -> ConnectionSpec,
    # its address and options as arguments. None: it opens none of its own
    connection: ClassVar[Optional[Callable[..., ConnectionSpec]]] = None

    @classmethod
    def recommended_connection(cls) -> Optional[Dict[str, Any]]:
        """The connection Setup offers for it, as a profile holds one. A driver
        whose connection() needs where it is recommends the rest instead."""
        return None if cls.connection is None else connection_fields(cls.connection())

    @classmethod
    def passport(cls, channel: Optional[Hashable] = None) -> Mapping[str, Limit]:
        """Limits of the instrument (None), or of one channel or sub-device."""
        return cls.channel_limits.get(channel, cls.limits)

    @classmethod
    def fixed_channels(cls) -> Tuple[Hashable, ...]:
        # Channels reinterpreted as sub-devices (SIS DEVs) are not shown on their own
        if any(kind.accessor == "channel" for kind in cls.subdevices.values()):
            return ()
        return tuple(cls.channel_keys)

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

    def part(self, accessor: str, key: Hashable) -> Any:
        """The part a channel or sub-device refers to: channel(key), ctrl(key), ..."""
        method = getattr(self, accessor, None)
        if not callable(method):
            raise ConfigurationError(f"{self.name} has no {accessor!r} parts")
        return method(key)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


class ScpiInstrument(Instrument, Identifiable, RawCommands):
    """Message based instrument: text commands over a Transport."""

    def __init__(self, transport: Transport, *, name: Optional[str] = None):
        super().__init__(name=name)
        self.transport = transport

    def write(self, command: str) -> None:
        self.transport.write(command)

    def query(self, command: str) -> str:
        return self.transport.query(command).strip()

    def send_raw(self, command: str, answer: bool) -> Optional[str]:
        """A command as typed (RawCommands); its answer when one is read."""
        if answer:
            return self.query(command)
        self.write(command)
        return None

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

    def errors(self) -> List[str]:
        """The instrument's error queue (SYST:ERR?), read until it answers
        code 0 ("+0,\"No error\""): the answers with an error, oldest first."""
        found = []
        for _ in range(ERROR_QUEUE_READS):
            answer = self.query("SYST:ERR?")
            code = self._parse("SYST:ERR?", answer, lambda a: int(a.split(",")[0]))
            if code == 0:
                break
            found.append(answer)
        return found

    def close(self) -> None:
        self.transport.close()
