"""Adapters a configured device puts over an instrument part.

An adapter delegates every attribute it doesn't override to the wrapped part.
"""

from typing import Any, Dict

from thzdaq_core.errors import StationError


class PortAdapter:
    def __init__(self, target: Any):
        self.target = target

    def __getattr__(self, name: str) -> Any:
        # Only called for attributes missing on the adapter itself
        if name == "target":
            raise AttributeError(name)
        return getattr(self.target, name)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.target!r})"


class AttributePort(PortAdapter):
    """A configured device over a shared part, with its own attributes.

    Two SIS configs on one DEV (different mixers, offsets) share the channel
    object; the attributes are applied before every call through this device.
    """

    def __init__(self, target: Any, attributes: Dict[str, Any]):
        super().__init__(target)
        for name in attributes:
            if not hasattr(target, name):
                raise StationError(f"{target!r} has no attribute {name!r}")
        self.attributes = dict(attributes)
        self.apply()

    def apply(self) -> None:
        for name, value in self.attributes.items():
            setattr(self.target, name, value)

    def __getattr__(self, name: str) -> Any:
        if name in ("target", "attributes"):
            raise AttributeError(name)
        if name in self.__dict__.get("attributes", {}):
            return self.attributes[name]
        value = getattr(self.target, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            self.apply()
            return value(*args, **kwargs)

        return call

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__dict__.get("attributes", {}):
            self.attributes[name] = value
            setattr(self.target, name, value)
        else:
            super().__setattr__(name, value)
