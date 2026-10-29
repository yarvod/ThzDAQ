import logging
import threading
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    Hashable,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)

from thzdaq_instruments import default_registry
from thzdaq_instruments.actions import Action, actions_for
from thzdaq_instruments.capabilities import OutputProtection, capabilities_of
from thzdaq_instruments.errors import InstrumentError
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.quantities import (
    CURRENT_SET,
    VOLTAGE_SET,
    Quantity,
    quantities_for,
    quantities_of,
)
from thzdaq_instruments.registry import DriverRegistry
from thzdaq_instruments.transport.pool import TransportPool, default_pool

from thzdaq_core.domain.data.measurement import DeviceUse
from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.config import (
    CHANNEL_SEPARATOR,
    InstrumentConfig,
    StationConfig,
    channel_ref,
)
from thzdaq_core.domain.station.kinds import DeviceKind, kind_capabilities, kinds_for
from thzdaq_core.domain.station.ports import GuardedPort, Pause
from thzdaq_core.domain.station.profile import station_to_dict
from thzdaq_core.domain.station.safety import Guard

logger = logging.getLogger(__name__)

Capabilities = Union[Type, Tuple[Type, ...]]
Requirements = Mapping[str, Capabilities]
# (slot, quantity key, values) a run sets the device of a slot to
Planned = Tuple[str, str, Sequence[float]]

NUMBERS = ("float", "int")  # kinds of quantities a guard checks and ramps

INSTRUMENT = "instrument"
CHANNEL = "channel"


def _as_tuple(capabilities: Capabilities) -> Tuple[Type, ...]:
    return capabilities if isinstance(capabilities, tuple) else (capabilities,)


@dataclass(frozen=True)
class DeviceInfo:
    """A device as lists and combo boxes show it; known without opening anything."""

    ref: str
    title: str
    instrument: str
    kind: str  # "instrument", "channel" or a device kind (sis_bias, ...)
    channel: Optional[Hashable]
    capabilities: Tuple[type, ...]
    configured: bool = False

    def provides(self, capabilities: Capabilities) -> bool:
        return all(c in self.capabilities for c in _as_tuple(capabilities))


@dataclass(frozen=True)
class ConnectionInfo:
    """A physical connection several instruments may share (a Prologix, a socket)."""

    key: tuple
    label: str
    instruments: Tuple[str, ...]  # titles
    open: bool
    broken: bool


KIND_LABELS = {
    "socket": "Socket",
    "prologix": "Prologix",
    "prologix_usb": "Prologix USB",
    "serial": "Serial",
    "visa": "VISA",
}


class Station:
    """Runtime bench: opens instruments on first use and hands out devices.

    Measurements get devices by ref and check capabilities (station.require),
    never drivers, so the same procedure runs on any bench or simulator. Every
    device is handed out guarded (GuardedPort): the passport of its driver and
    the safety section of the profile hold whoever sets it.
    """

    def __init__(
        self,
        config: StationConfig,
        *,
        pause: Pause,
        registry: Optional[DriverRegistry] = None,
        pool: Optional[TransportPool] = None,
        simulate: bool = False,
        lively: bool = False,
    ):
        self.config = config.validate()
        self.pause = pause  # how ramps outside measurements wait between steps
        self.registry = registry or default_registry()
        self.pool = pool
        self.simulate = simulate
        # Simulators drift and get noisy, as a bench does (the app); tests keep
        # exact values
        self.lively = lively
        self._instruments: Dict[str, Instrument] = {}
        self._devices: Dict[str, GuardedPort] = {}
        self._lock = threading.RLock()
        self._check_safety()

    @property
    def name(self) -> str:
        return self.config.name

    def __repr__(self):
        return f"Station({self.name!r}, simulate={self.simulate})"

    # Instruments
    def _spec(self, instrument_id: str) -> InstrumentConfig:
        spec = self.config.instruments.get(instrument_id)
        if spec is None:
            raise StationError(f"{self.name}: no instrument {instrument_id!r}")
        return spec

    def simulated(self, instrument_id: str) -> bool:
        return self.simulate or self._spec(instrument_id).simulate

    def driver_class(self, instrument_id: str) -> Type[Instrument]:
        """The class that will be opened: the simulator when simulating."""
        info = self.registry.get(self._spec(instrument_id).driver)
        if self.simulated(instrument_id) and info.sim is not None:
            return info.sim
        return info.cls

    def kinds(self, instrument_id: str) -> Dict[str, DeviceKind]:
        return kinds_for(self.driver_class(instrument_id))

    def instrument(self, instrument_id: str) -> Instrument:
        with self._lock:
            if instrument_id in self._instruments:
                return self._instruments[instrument_id]
            spec = self._spec(instrument_id)
            simulate = self.simulated(instrument_id)
            logger.info(
                f"[{self.name}] opening {instrument_id} ({spec.driver}"
                f"{', simulated' if simulate else ''})"
            )
            instrument = self.registry.open(
                spec.driver,
                spec.connection,
                pool=self.pool,
                name=spec.title or instrument_id,
                simulate=simulate,
                **(spec.sim_options if simulate else spec.options),
            )
            if simulate or self.registry.get(spec.driver).simulated:
                self._apply_settings(instrument, spec.settings)
                if self.lively and hasattr(instrument, "liven"):
                    instrument.liven()
            if simulate and hasattr(instrument, "load_position"):
                # A simulated detector sees the simulated load of this bench:
                # hot/cold give a receiver's Y, not the drift of two sweeps
                instrument.load_position = self._simulated_load
            self._instruments[instrument_id] = instrument
            self._protect(instrument_id)
            return instrument

    def _protect(self, instrument_id: str) -> None:
        """Supply outputs of the instrument keep the bench maxima of voltage
        and current themselves (OVP, OCP), when the profile asks for it."""
        safety = self.config.safety
        if not safety.hardware_protection:
            return
        for ref, limits in safety.limits.items():
            info = self.info(ref)
            if info.instrument != instrument_id or not info.provides(OutputProtection):
                continue
            voltage, current = (limits.get(q.key) for q in (VOLTAGE_SET, CURRENT_SET))
            if voltage or current:
                self._part(ref).set_protection(
                    voltage.maximum if voltage else None,
                    current.maximum if current else None,
                )

    def _simulated_load(self) -> Optional[str]:
        """Where the open simulated load switch (a chopper) is: hot, cold, None."""
        for instrument_id, instrument in list(self._instruments.items()):
            if self.simulated(instrument_id) and hasattr(instrument, "load_state"):
                return instrument.load_state()
        return None

    @staticmethod
    def _apply_settings(instrument: Instrument, settings: Dict[str, Any]) -> None:
        """A simulator starts configured as the profile says (a real one is not touched)."""
        for quantity in quantities_of(instrument):
            if quantity.persistent and quantity.settable and quantity.key in settings:
                quantity.write(instrument, settings[quantity.key])

    def is_open(self, instrument_id: str) -> bool:
        return instrument_id in self._instruments

    def close_instrument(self, instrument_id: str) -> None:
        with self._lock:
            instrument = self._instruments.pop(instrument_id, None)
            prefix = instrument_id + CHANNEL_SEPARATOR
            for ref in list(self._devices):
                if (
                    ref == instrument_id
                    or ref.startswith(prefix)
                    or self._owner(ref) == instrument_id
                ):
                    del self._devices[ref]
            if instrument is not None:
                try:
                    instrument.close()
                except Exception as e:
                    logger.error(f"[{self.name}] closing {instrument_id}: {e}")

    @property
    def opened(self) -> Tuple[str, ...]:
        return tuple(self._instruments)

    # Connections
    @property
    def transport_pool(self) -> TransportPool:
        return self.pool or default_pool

    def connections(self) -> List[ConnectionInfo]:
        """Shared connections of the profile and their state (open, broken)."""
        status = {link.key: link for link in self.transport_pool.links()}
        users: Dict[tuple, List[str]] = {}
        labels: Dict[tuple, str] = {}
        for instrument_id, spec in self.config.instruments.items():
            connection = spec.connection
            if connection is None or not connection.is_message_based:
                continue
            if self.simulated(instrument_id):
                continue
            key = connection.link_key
            users.setdefault(key, []).append(spec.title or instrument_id)
            where = connection.host or connection.serial_port or connection.resource
            port = f":{connection.port}" if connection.host and connection.port else ""
            labels[
                key
            ] = f"{KIND_LABELS.get(connection.kind, connection.kind)} {where}{port}"
        return [
            ConnectionInfo(
                key, labels[key], tuple(names),
                key in status and status[key].open,
                key in status and status[key].broken,
            )
            for key, names in users.items()
        ]  # fmt: skip

    def reset_connection(self, key: tuple) -> bool:
        return self.transport_pool.reset(key)

    def close_idle_connections(self, max_idle: float) -> List[tuple]:
        """Let go of TCP connections unused for max_idle seconds (a stopped
        monitor): the instrument leaves remote mode and other clients may
        connect; the next command reconnects."""
        return self.transport_pool.close_idle(max_idle)

    def abort(self, refs) -> None:
        """Break commands blocked on the connections of these devices.

        Shared connections are aborted (the next command reconnects); drivers
        with their own connection (HTTP, Modbus) are closed and reopen on use.
        """
        instruments = set()
        for ref in refs:
            try:
                instruments.add(self.info(ref).instrument)
            except StationError:
                continue
        for instrument_id in instruments:
            connection = self._spec(instrument_id).connection
            if connection is not None and connection.is_message_based:
                self.transport_pool.abort(connection.link_key)
            elif instrument_id in self._instruments:
                self.close_instrument(instrument_id)

    # Devices
    def _owner(self, ref: str) -> Optional[str]:
        found = self.config.find_device(ref)
        return found[0] if found else None

    def devices(self) -> List[DeviceInfo]:
        """Every device: instruments, their fixed channels, configured devices."""
        result = []
        for instrument_id, spec in self.config.instruments.items():
            title = spec.title or instrument_id
            try:
                cls = self.driver_class(instrument_id)
            except InstrumentError:
                cls = None
            result.append(
                DeviceInfo(
                    instrument_id, title, instrument_id, INSTRUMENT, None,
                    capabilities_of(cls),
                )
            )  # fmt: skip
            if cls is not None:
                for key in cls.fixed_channels():
                    result.append(
                        DeviceInfo(
                            channel_ref(instrument_id, key), channel_title(title, key),
                            instrument_id, CHANNEL, key,
                            capabilities_of(cls.channel_class),
                        )
                    )  # fmt: skip
            kinds = kinds_for(cls) if cls is not None else {}
            for device_id, device in spec.devices.items():
                kind = kinds.get(device.kind)
                target = cls
                if device.channel is not None and cls is not None:
                    target = cls.channel_class
                result.append(
                    DeviceInfo(
                        device_id, device.title or device_id, instrument_id,
                        device.kind, device.channel,
                        kind_capabilities(kind, target) if kind else (),
                        configured=True,
                    )
                )  # fmt: skip
        return result

    def info(self, ref: str) -> DeviceInfo:
        for item in self.devices():
            if item.ref == ref:
                return item
        raise StationError(f"{self.name}: no device {ref!r}")

    def title(self, ref: str) -> str:
        try:
            return self.info(ref).title
        except StationError:
            return ref

    def find(self, capabilities: Capabilities) -> List[DeviceInfo]:
        return [item for item in self.devices() if item.provides(capabilities)]

    def __contains__(self, ref: str) -> bool:
        return any(item.ref == ref for item in self.devices())

    def __getitem__(self, ref: str) -> Any:
        return self.device(ref)

    def device(self, ref: str) -> GuardedPort:
        """The device of a ref, guarded; opens its instrument on first use."""
        with self._lock:
            if ref not in self._devices:
                part = self._part(ref)
                guarded = [
                    q for q in self.quantities(ref) if q.setters and q.kind in NUMBERS
                ]
                self._devices[ref] = GuardedPort(
                    part, self.guard(ref), guarded, self.pause
                )
            return self._devices[ref]

    def _part(self, ref: str) -> Any:
        if ref in self.config.instruments:
            return self.instrument(ref)
        if CHANNEL_SEPARATOR in ref:
            instrument_id, key = ref.split(CHANNEL_SEPARATOR, 1)
            cls = self.driver_class(instrument_id)
            matches = [k for k in cls.fixed_channels() if str(k) == key]
            if not matches:
                raise StationError(f"{self.name}: {instrument_id} has no channel {key}")
            return self.instrument(instrument_id).channel(matches[0])
        return self._build_configured(ref)

    def _build_configured(self, device_id: str) -> Any:
        found = self.config.find_device(device_id)
        if found is None:
            raise StationError(f"{self.name}: no device {device_id!r}")
        instrument_id, spec = found
        kind = self.kinds(instrument_id).get(spec.kind)
        if kind is None:
            raise StationError(
                f"device {device_id!r}: {self._spec(instrument_id).driver} "
                f"has no device kind {spec.kind!r}"
            )
        instrument = self.instrument(instrument_id)
        if kind.accessor is not None:
            if spec.channel is None:
                raise StationError(f"device {device_id!r}: channel is required")
            part = instrument.part(kind.accessor, spec.channel)
        elif spec.channel is not None:
            part = instrument.channel(spec.channel)
        else:
            part = instrument
        try:
            return kind.build(part, spec.settings)
        except TypeError as e:
            raise StationError(f"device {device_id!r}: {e}") from e

    def part_class(self, ref: str) -> type:
        """The class of the part a device is, known without opening anything."""
        info = self.info(ref)
        cls = self.driver_class(info.instrument)
        if info.kind == INSTRUMENT:
            return cls
        if info.kind == CHANNEL:
            return cls.channel_class
        kind = self.kinds(info.instrument).get(info.kind)
        if kind and kind.part_class:
            return kind.part_class
        return cls.channel_class if info.channel is not None else cls

    def quantities(self, ref: str) -> List[Quantity]:
        """Values a device can read or set, known without opening anything."""
        own = getattr(self.part_class(ref), "quantities", ())
        return quantities_for(self.info(ref).capabilities, own)

    def passport(self, ref: str) -> Mapping[str, Limit]:
        """What the instrument of a device accepts at all: its real driver's
        passport, also when it is simulated."""
        info = self.info(ref)
        driver = self.registry.get(self._spec(info.instrument).driver).cls
        return driver.passport(info.channel)

    def guard(self, ref: str) -> Guard:
        """What a device accepts and how it changes, known without opening it."""
        return Guard(ref, self.passport(ref), self.config.safety.limits.get(ref, {}))

    def limit_problems(self, ref: str, key: str, values: Iterable[float]) -> List[str]:
        """Why these values of a quantity cannot be set; empty when they can."""
        found = [q for q in self.quantities(ref) if q.key == key]
        if not found:
            return [f"{ref} has no {key}"]
        guard = self.guard(ref)
        problems = (guard.problem(found[0], value) for value in values)
        return list(dict.fromkeys(p for p in problems if p))

    def actions(self, ref: str) -> List[Action]:
        """What a device does on request, known without opening anything: from
        its capabilities, its driver and, for a configured device, its kind."""
        own = list(getattr(self.part_class(ref), "actions", ()))
        found = self.config.find_device(ref)
        if found is not None:
            instrument_id, spec = found
            kind = self.kinds(instrument_id).get(spec.kind)
            if kind is not None:
                own += kind.actions(spec.channel, spec.metadata)
        return actions_for(self.info(ref).capabilities, own)

    def device_use(self, ref: str) -> DeviceUse:
        """How a device was set up, for measurement metadata."""
        try:
            info = self.info(ref)
        except StationError:
            return DeviceUse(ref)
        found = self.config.find_device(ref)
        return DeviceUse(
            ref=ref,
            title=info.title,
            instrument=info.instrument,
            driver=self._spec(info.instrument).driver,
            kind=info.kind,
            settings=dict(found[1].settings) if found else {},
        )

    def require(
        self,
        devices: Mapping[str, str],
        requirements: Requirements,
        pause: Pause,
        planned: Iterable[Planned] = (),
    ) -> Dict[str, GuardedPort]:
        """Devices for measurement slots: capabilities checked, and the values
        the run sets them to checked against their limits; every problem at
        once. Their ramps wait with pause (a run's, which a cancel stops)."""
        problems = []
        found = {}
        for slot, capabilities in requirements.items():
            ref = devices.get(slot)
            if not ref:
                problems.append(f"no device chosen for {slot!r}")
                continue
            try:
                device = self.device(ref)
            except (InstrumentError, StationError) as e:
                problems.append(f"{slot}: {e}")
                continue
            missing = [
                c.__name__ for c in _as_tuple(capabilities) if not isinstance(device, c)
            ]
            if missing:
                problems.append(f"{slot}: {self.title(ref)} lacks {', '.join(missing)}")
                continue
            found[slot] = device
        for slot, key, values in planned:
            if slot in found:
                for problem in self.limit_problems(devices[slot], key, values):
                    problems.append(f"{slot}: {problem}")
        if problems:
            raise StationError(f"{self.name}: " + "; ".join(problems))
        return {slot: device.pausing(pause) for slot, device in found.items()}

    # Lifecycle and metadata
    def _check_safety(self) -> None:
        """The safety section guards devices and quantities that exist: a
        misspelt one would leave a device unguarded."""
        problems = []
        safety = self.config.safety
        for ref in safety.refs():
            try:
                settable = {q.key: q for q in self.quantities(ref) if q.settable}
            except (InstrumentError, StationError) as e:
                problems.append(f"safety of {ref}: {e}")
                continue
            for key in safety.limits.get(ref, {}):
                quantity = settable.get(key)
                if quantity is None or quantity.kind not in NUMBERS:
                    problems.append(f"safety of {ref}: {key} is no number it sets")
            for key, value in safety.safe_state.get(ref, {}).items():
                if key not in settable:
                    problems.append(f"safe state of {ref}: it does not set {key}")
                    continue
                try:
                    settable[key].parse(value)
                except ValueError as e:
                    problems.append(f"safe state of {ref}: {e}")
        if problems:
            raise StationError(f"{self.name}: " + "; ".join(problems))

    def reconfigure(self, config: StationConfig) -> None:
        """Take an edited profile; instruments whose setup changed are reopened,
        open supplies take changed protection levels."""
        # A station of the edited profile checks it; it opens nothing
        Station(
            config, pause=self.pause, registry=self.registry, simulate=self.simulate
        )
        with self._lock:
            for instrument_id in list(self._instruments):
                old = self.config.instruments.get(instrument_id)
                new = config.instruments.get(instrument_id)
                if new is None or old is None or _opening_changed(old, new):
                    self.close_instrument(instrument_id)
            protection_changed = config.safety != self.config.safety
            self.config = config
            self._devices.clear()
            if protection_changed:
                for instrument_id in list(self._instruments):
                    self._protect(instrument_id)

    def snapshot(self, refs: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        """Profile plus identities of opened instruments, for measurement metadata.

        refs: only the instruments of these devices are asked (a measurement's
        own): an unrelated one that does not answer (a chopper used earlier)
        must not delay or break the start. A failed identity is recorded.
        """
        wanted = None
        if refs is not None:
            wanted = set()
            for ref in refs:
                try:
                    wanted.add(self.info(ref).instrument)
                except StationError:
                    continue
        identities = {}
        for instrument_id, instrument in list(self._instruments.items()):
            if wanted is not None and instrument_id not in wanted:
                continue
            identify = getattr(instrument, "identify", None)
            try:
                identities[instrument_id] = identify() if identify else None
            except Exception as e:  # metadata only: never stops a measurement
                identities[instrument_id] = f"error: {e.__class__.__name__}: {e}"
        return {
            "station": station_to_dict(self.config),
            "simulate": self.simulate,
            "identities": identities,
        }

    def close(self) -> None:
        with self._lock:
            for instrument_id in reversed(list(self._instruments)):
                self.close_instrument(instrument_id)
            self._devices.clear()

    def __enter__(self) -> "Station":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def channel_title(instrument_title: str, key: Hashable) -> str:
    return (
        f"{instrument_title} CH{key}"
        if isinstance(key, int)
        else f"{instrument_title} {key}"
    )


def _opening_changed(old: InstrumentConfig, new: InstrumentConfig) -> bool:
    keys = ("driver", "connection", "options", "simulate", "sim_options")
    return any(getattr(old, k) != getattr(new, k) for k in keys)
