"""What a device part offers: the quantities and actions of the capabilities its
class declares, then its own (a driver's ``quantities`` and ``actions`` class
attributes; one with the key of a capability's replaces it).

A part handed out in a port (thzdaq_core: the guard, the attributes of a
configured device) offers what the part itself does: a port names the part it
wraps by its ``target``, and the part's class is asked.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from thzdaq_instruments.actions import Action
from thzdaq_instruments.capabilities import capabilities_of
from thzdaq_instruments.quantities import Quantity, pick


def _by_key(given: Iterable[Iterable[Any]], extra: Iterable[Any]) -> List[Any]:
    """What the capabilities give (quantities, actions), the first of each key,
    then the extra (driver) ones; an extra one replaces a capability's."""
    found: Dict[str, Any] = {}
    for items in given:
        for item in items:
            found.setdefault(item.key, item)
    found.update((item.key, item) for item in extra)
    return list(found.values())


def quantities_for(
    capabilities: Iterable[type], extra: Iterable[Quantity] = ()
) -> List[Quantity]:
    """Quantities of the given capabilities, then the extra (driver) ones."""
    return _by_key((c.capability_quantities for c in capabilities), extra)


def actions_for(
    capabilities: Iterable[type], extra: Iterable[Action] = ()
) -> List[Action]:
    """Actions of the given capabilities, then the extra (driver) ones."""
    return _by_key((c.capability_actions for c in capabilities), extra)


def part_of(target: Any) -> Any:
    """The instrument part a device is: what its ports wrap, or itself."""
    while hasattr(target, "target"):
        target = target.target
    return target


def declared(target: Any, attribute: str) -> Tuple[Tuple[type, ...], Tuple[Any, ...]]:
    """Capabilities of a device part's class and what the class declares under
    the attribute (quantities, actions)."""
    return declared_by(type(part_of(target)), attribute)


def declared_by(cls: type, attribute: str) -> Tuple[Tuple[type, ...], Tuple[Any, ...]]:
    """Capabilities of a part class and what it declares under the attribute."""
    return capabilities_of(cls), tuple(getattr(cls, attribute, ()))


def class_quantities(cls: type) -> List[Quantity]:
    """Quantities every part of this class has, known without one."""
    return quantities_for(*declared_by(cls, "quantities"))


def quantities_of(target: Any) -> List[Quantity]:
    """Quantities of a device part: from its capabilities, then its own ones."""
    return class_quantities(type(part_of(target)))


def actions_of(target: Any) -> List[Action]:
    """Actions of a device part: from its capabilities, then its own ones."""
    return actions_for(*declared(target, "actions"))


def read_values(
    target: Any, quantities: Optional[Iterable[Quantity]] = None
) -> Dict[str, Any]:
    """Read every readable quantity, calling a shared source (measure()) once."""
    values: Dict[str, Any] = {}
    sources: Dict[int, Any] = {}
    for quantity in quantities_of(target) if quantities is None else quantities:
        if not quantity.readable:
            continue
        if quantity.source is not None:
            key = id(quantity.source)
            if key not in sources:
                sources[key] = quantity.source(target)
            values[quantity.key] = pick(sources[key], quantity.field)
        else:
            values[quantity.key] = quantity.get(target)
    return values
