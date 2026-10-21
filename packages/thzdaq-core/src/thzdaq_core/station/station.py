import logging
import threading
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Type, Union

from thzdaq_instruments import default_registry
from thzdaq_instruments.errors import InstrumentError
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.registry import DriverRegistry
from thzdaq_instruments.transport.pool import TransportPool

from thzdaq_core.errors import StationError
from thzdaq_core.station.config import StationConfig
from thzdaq_core.station.ports import build_adapter
from thzdaq_core.station.storage import PathLike, load_station, station_to_dict

logger = logging.getLogger(__name__)

Capabilities = Union[Type, Tuple[Type, ...]]
Requirements = Mapping[str, Capabilities]


def _as_tuple(capabilities: Capabilities) -> Tuple[Type, ...]:
    return capabilities if isinstance(capabilities, tuple) else (capabilities,)


class Station:
    """Runtime bench: opens instruments on first use and hands out roles.

    Measurements ask for roles by name and capability (station.require(...)),
    never for drivers, so the same procedure runs on any bench or simulator.
    """

    def __init__(
        self,
        config: StationConfig,
        *,
        registry: Optional[DriverRegistry] = None,
        pool: Optional[TransportPool] = None,
        simulate: bool = False,
    ):
        self.config = config.validate()
        self.registry = registry or default_registry()
        self.pool = pool
        self.simulate = simulate
        self._instruments: Dict[str, Instrument] = {}
        self._roles: Dict[str, Any] = {}
        self._lock = threading.RLock()

    @classmethod
    def load(cls, path: PathLike, **kwargs) -> "Station":
        return cls(load_station(path), **kwargs)

    @property
    def name(self) -> str:
        return self.config.name

    def __repr__(self):
        return f"Station({self.name!r}, simulate={self.simulate})"

    # Instruments
    def instrument(self, instrument_id: str) -> Instrument:
        with self._lock:
            if instrument_id in self._instruments:
                return self._instruments[instrument_id]
            spec = self.config.instruments.get(instrument_id)
            if spec is None:
                raise StationError(f"{self.name}: no instrument {instrument_id!r}")
            simulate = self.simulate or spec.simulate
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
            self._instruments[instrument_id] = instrument
            return instrument

    @property
    def opened(self) -> Tuple[str, ...]:
        return tuple(self._instruments)

    # Roles
    def __contains__(self, role: str) -> bool:
        return role in self.config.roles

    def __getitem__(self, role: str) -> Any:
        return self.role(role)

    def role(self, role: str) -> Any:
        with self._lock:
            if role in self._roles:
                return self._roles[role]
            spec = self.config.roles.get(role)
            if spec is None:
                raise StationError(f"{self.name}: no role {role!r}")
            part: Any = self.instrument(spec.instrument)
            if spec.channel is not None:
                accessor = getattr(part, spec.accessor, None)
                if not callable(accessor):
                    raise StationError(
                        f"role {role!r}: {spec.instrument} has no {spec.accessor}()"
                    )
                part = accessor(spec.channel)
            for attribute, value in spec.attributes.items():
                if not hasattr(part, attribute):
                    raise StationError(
                        f"role {role!r}: {part!r} has no attribute {attribute!r}"
                    )
                setattr(part, attribute, value)
            port = build_adapter(spec.adapter, part, spec.options)
            self._roles[role] = port
            return port

    def require(self, requirements: Requirements) -> Dict[str, Any]:
        """Build the roles and check their capabilities; report every problem at once."""
        problems = []
        ports = {}
        for role, capabilities in requirements.items():
            if role not in self:
                problems.append(f"role {role!r} is not configured")
                continue
            try:
                port = self.role(role)
            except (InstrumentError, StationError) as e:
                problems.append(f"role {role!r}: {e}")
                continue
            missing = [
                c.__name__ for c in _as_tuple(capabilities) if not isinstance(port, c)
            ]
            if missing:
                problems.append(f"role {role!r} lacks {', '.join(missing)}")
                continue
            ports[role] = port
        if problems:
            raise StationError(f"{self.name}: " + "; ".join(problems))
        return ports

    def missing_roles(self, roles: Iterable[str]) -> Tuple[str, ...]:
        """Roles absent from the profile, without opening anything."""
        return tuple(role for role in roles if role not in self)

    # Lifecycle and metadata
    def snapshot(self) -> Dict[str, Any]:
        """Profile plus identities of opened instruments, for measurement metadata."""
        identities = {}
        for instrument_id, instrument in self._instruments.items():
            identify = getattr(instrument, "identify", None)
            try:
                identities[instrument_id] = identify() if identify else None
            except InstrumentError as e:
                identities[instrument_id] = f"error: {e}"
        return {
            "station": station_to_dict(self.config),
            "simulate": self.simulate,
            "identities": identities,
        }

    def close(self) -> None:
        with self._lock:
            for instrument_id, instrument in reversed(list(self._instruments.items())):
                try:
                    instrument.close()
                except Exception as e:  # keep closing the rest
                    logger.error(f"[{self.name}] closing {instrument_id}: {e}")
            self._instruments.clear()
            self._roles.clear()

    def __enter__(self) -> "Station":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
