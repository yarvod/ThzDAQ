from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, Type

from thzdaq_instruments.capabilities import capabilities_of
from thzdaq_instruments.errors import ConfigurationError, UnknownDriverError
from thzdaq_instruments.instrument import Instrument, ScpiInstrument
from thzdaq_instruments.transport.base import ConnectionSpec
from thzdaq_instruments.transport.pool import TransportPool, default_pool


@dataclass(frozen=True)
class DriverInfo:
    key: str
    cls: Type[Instrument]
    title: str
    sim: Optional[Type[Instrument]] = None
    simulated: bool = False

    @property
    def capabilities(self) -> Tuple[type, ...]:
        return capabilities_of(self.cls)

    @property
    def channel_capabilities(self) -> Tuple[type, ...]:
        return capabilities_of(self.cls.channel_class)

    def provides(self, capability: type) -> bool:
        return (
            capability in self.capabilities or capability in self.channel_capabilities
        )


class DriverRegistry:
    """Catalog of drivers: key -> class. Capabilities are derived from classes."""

    def __init__(self):
        self._drivers: Dict[str, DriverInfo] = {}

    def register(
        self,
        key: str,
        cls: Optional[Type[Instrument]] = None,
        *,
        title: Optional[str] = None,
        sim: Optional[Type[Instrument]] = None,
        simulated: bool = False,
        replace: bool = False,
    ):
        """Register a driver; usable as ``registry.register(key, Cls)`` or a decorator."""

        def decorator(driver_cls: Type[Instrument]) -> Type[Instrument]:
            if key in self._drivers and not replace:
                raise ConfigurationError(f"Driver {key!r} is already registered")
            self._drivers[key] = DriverInfo(
                key=key,
                cls=driver_cls,
                title=title or driver_cls.__name__,
                sim=sim,
                simulated=simulated,
            )
            return driver_cls

        if cls is not None:
            return decorator(cls)
        return decorator

    def get(self, key: str) -> DriverInfo:
        try:
            return self._drivers[key]
        except KeyError:
            raise UnknownDriverError(f"Driver {key!r} is not registered") from None

    def __contains__(self, key: str) -> bool:
        return key in self._drivers

    def all(self) -> List[DriverInfo]:
        return list(self._drivers.values())

    def find(self, capability: type) -> List[DriverInfo]:
        return [info for info in self._drivers.values() if info.provides(capability)]

    def open(
        self,
        key: str,
        connection: Optional[ConnectionSpec] = None,
        *,
        pool: Optional[TransportPool] = None,
        name: Optional[str] = None,
        simulate: bool = False,
        **options,
    ) -> Instrument:
        """Create a connected driver (or its simulator with simulate=True)."""
        info = self.get(key)
        if simulate or info.simulated:
            sim_cls = info.cls if info.simulated else info.sim
            if sim_cls is None:
                raise ConfigurationError(f"Driver {key!r} has no simulator")
            return sim_cls(name=name, **options)

        if not issubclass(info.cls, ScpiInstrument):
            return info.cls(connection=connection, name=name, **options)
        if connection is None:
            raise ConfigurationError(f"Driver {key!r} requires a connection")
        transport = (pool or default_pool).acquire(connection)
        try:
            return info.cls(transport, name=name, **options)
        except BaseException:
            transport.close()
            raise


@lru_cache(maxsize=1)
def default_registry() -> DriverRegistry:
    """Registry with every built-in driver and simulator."""
    from thzdaq_instruments.drivers import register_drivers
    from thzdaq_instruments.sim import register_simulators

    registry = DriverRegistry()
    register_drivers(registry)
    register_simulators(registry)
    return registry
