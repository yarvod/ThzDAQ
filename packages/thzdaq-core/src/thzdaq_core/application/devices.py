"""Reading and setting device quantities, each in its instrument's lane; what is
read or set becomes the known value, a set is an event."""

from typing import Any, Callable, Dict, Iterable, List, Optional

from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import QuantitySet
from thzdaq_instruments.quantities import Quantity, read_values

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.values import KnownValues


class DeviceAccess:
    def __init__(self, bench: Bench, known: KnownValues, events: EventBus):
        self.bench = bench
        self.known = known
        self.events = events

    def quantities(self, ref: str) -> List[Quantity]:
        self.bench.info(ref)  # an unknown device is NOT_FOUND
        return self.bench.station.quantities(ref)

    def quantity(self, ref: str, key: str) -> Quantity:
        for quantity in self.quantities(ref):
            if quantity.key == key:
                return quantity
        keys = ", ".join(q.key for q in self.quantities(ref))
        raise LabError(ErrorCode.NOT_FOUND, f"{ref} has no {key!r}", f"it has: {keys}")

    def readable(
        self, ref: str, keys: Optional[Iterable[str]] = None
    ) -> List[Quantity]:
        """Every readable quantity, or the listed ones (all must be readable)."""
        wanted = (
            [q for q in self.quantities(ref) if q.readable]
            if keys is None
            else [self.quantity(ref, key) for key in keys]
        )
        unreadable = [q.key for q in wanted if not q.readable]
        if unreadable:
            raise LabError(ErrorCode.NOT_ALLOWED, f"{ref}: {unreadable} cannot be read")
        return wanted

    def read(self, ref: str, keys: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        wanted = self.readable(ref, keys)
        values = self.bench.run(ref, lambda device: read_values(device, wanted))
        self.known.update(ref, values)
        return values

    def read_later(
        self,
        ref: str,
        keys: Optional[Iterable[str]],
        deliver: Callable[[Optional[Dict[str, Any]], Optional[BaseException]], None],
    ) -> None:
        """A read that does not wait (a poll): deliver(values, error) in the lane."""
        wanted = self.readable(ref, keys)

        def done(values, error):
            if error is None:
                self.known.update(ref, values)
            deliver(values, error)

        self.bench.submit(ref, lambda device: read_values(device, wanted), done)

    def write(self, ref: str, key: str, value: Any, origin: str) -> Any:
        """Set a quantity; the value as given (a text may carry its unit) is
        parsed by the quantity. Returns the value set."""
        quantity = self.quantity(ref, key)
        if not quantity.settable:
            raise LabError(ErrorCode.NOT_ALLOWED, f"{ref}: {key} cannot be set")
        try:
            parsed = quantity.parse(value)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        before = self.known.get(ref, key)
        self.bench.run(ref, lambda device: quantity.write(device, parsed))
        self.known.update(ref, {key: parsed})
        self.events.publish(QuantitySet(ref, key, parsed, before, origin))
        return parsed
