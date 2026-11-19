"""What a device part offers: the quantities and actions of the capabilities its
class declares, then its own (a driver's ``quantities`` and ``actions`` class
attributes; one with the key of a capability's replaces it).

A part handed out in a port (thzdaq_core: the guard, the attributes of a
configured device) offers what the part itself does: the port's class declares
the part's capabilities and its own quantities and actions, so it is asked as
the part is.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from thzdaq_instruments.actions import Action
from thzdaq_instruments.capabilities import capabilities_of
from thzdaq_instruments.quantities import Quantity, pick


def _by_key(
    given: Iterable[Tuple[type, Iterable[Any]]], extra: Iterable[Any]
) -> List[Any]:
    """What the capabilities give (quantities, actions), the first of each key
    (one of a capability that refines the first's replaces it), then the extra
    (driver) ones; an extra one replaces a capability's."""
    found: Dict[str, Tuple[type, Any]] = {}
    for capability, items in given:
        for item in items:
            known = found.get(item.key)
            if known is None or issubclass(capability, known[0]):
                found[item.key] = (capability, item)
    items = {key: item for key, (_, item) in found.items()}
    items.update((item.key, item) for item in extra)
    return list(items.values())


def quantities_for(
    capabilities: Iterable[type], extra: Iterable[Quantity] = ()
) -> List[Quantity]:
    """Quantities of the given capabilities, then the extra (driver) ones."""
    return _by_key(((c, c.capability_quantities) for c in capabilities), extra)


def actions_for(
    capabilities: Iterable[type], extra: Iterable[Action] = ()
) -> List[Action]:
    """Actions of the given capabilities, then the extra (driver) ones."""
    return _by_key(((c, c.capability_actions) for c in capabilities), extra)


def declared(target: Any, attribute: str) -> Tuple[Tuple[type, ...], Tuple[Any, ...]]:
    """Capabilities of a device part's class and what the class declares under
    the attribute (quantities, actions)."""
    return declared_by(type(target), attribute)


def declared_by(cls: type, attribute: str) -> Tuple[Tuple[type, ...], Tuple[Any, ...]]:
    """Capabilities of a part class and what it declares under the attribute."""
    return capabilities_of(cls), tuple(getattr(cls, attribute, ()))


def class_quantities(cls: type) -> List[Quantity]:
    """Quantities every part of this class has, known without one."""
    return quantities_for(*declared_by(cls, "quantities"))


def quantities_of(target: Any) -> List[Quantity]:
    """Quantities of a device part: from its capabilities, then its own ones."""
    return class_quantities(type(target))


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
