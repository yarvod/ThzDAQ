"""Actions: what a device does on request, beyond setting a quantity.

Like quantities, actions come from capabilities (a load switch turns to the
hot or the cold load, an analyzer reads a trace) and drivers add their own
(the chopper's continuous rotation) with the ``actions`` class attribute. An
action takes arguments with units and may return a result (a trace). One that
can harm the bench carries a warning, shown before it runs.

A rotator has no action: its angle is a settable quantity.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from thzdaq_instruments import capabilities as caps
from thzdaq_instruments.quantities import Kind, by_key, declared, parse_as


@dataclass(frozen=True)
class Argument:
    key: str
    title: str
    unit: str = ""  # SI symbol, as quantities
    kind: Kind = "float"
    default: Any = None  # None: the argument is required
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[Any, ...] = ()

    def parse(self, value: Any) -> Any:
        return parse_as(self, value)


@dataclass(frozen=True)
class Action:
    key: str
    title: str
    call: Callable[..., Any]  # call(target, **arguments)
    arguments: Tuple[Argument, ...] = ()
    danger: str = ""  # what may go wrong, shown before it runs; empty when safe
    # A read changes nothing on the device: a measurement sweeping it is not disturbed
    changes: bool = True
    help: str = ""

    def bind(self, given: Mapping[str, Any]) -> Dict[str, Any]:
        """The arguments as given (a text may carry its unit), parsed, with the
        defaults filled in; ValueError names what is wrong."""
        known = {argument.key for argument in self.arguments}
        unknown = sorted(set(given) - known)
        if unknown:
            raise ValueError(f"{self.key}: unknown arguments {unknown}")
        values = {}
        for argument in self.arguments:
            if argument.key in given:
                values[argument.key] = argument.parse(given[argument.key])
            elif argument.default is not None:
                values[argument.key] = argument.default
            else:
                raise ValueError(f"{self.key}: {argument.key} is required")
        return values

    def run(self, target: Any, arguments: Mapping[str, Any]) -> Any:
        return self.call(target, **self.bind(arguments))


def _configure_spectrum(target, center: float, span: float) -> None:
    target.set_center_frequency(center)
    target.set_span(span)


def _configure_network(
    target, start: float, stop: float, points: int, parameter: str
) -> None:
    target.set_frequency_range(start, stop)
    target.set_points(points)
    target.select_parameter(parameter)


TO_HOT = Action("to_hot", "Hot", lambda t: t.to_hot(), help="Turn to the hot load")
TO_COLD = Action("to_cold", "Cold", lambda t: t.to_cold(), help="Turn to the cold load")

TURN_ON = Action(
    "turn_on", "Turn on", lambda t: t.turn_on(),
    danger="Starts the compressor: the cold head runs",
)  # fmt: skip
TURN_OFF = Action(
    "turn_off", "Turn off", lambda t: t.turn_off(),
    danger="Stops the compressor: the cryostat warms up",
)  # fmt: skip

READ_TRACE = Action("read_trace", "Read trace", lambda t: t.read_trace(), changes=False)

CONFIGURE_SPECTRUM = Action(
    "configure", "Apply", _configure_spectrum,
    arguments=(
        Argument("center", "Center", "Hz", minimum=0),
        Argument("span", "Span", "Hz", minimum=0),
    ),
    help="Center frequency and span of the sweep",
)  # fmt: skip

CONFIGURE_NETWORK = Action(
    "configure", "Apply", _configure_network,
    arguments=(
        Argument("start", "Start", "Hz", minimum=0),
        Argument("stop", "Stop", "Hz", minimum=0),
        Argument("points", "Points", kind="int", minimum=2, maximum=100001),
        Argument("parameter", "S-parameter", kind="text", default="S11"),
    ),
    help="Frequency range, points and the S-parameter of the sweep",
)  # fmt: skip

CAPABILITY_ACTIONS: Dict[type, Tuple[Action, ...]] = {
    caps.LoadSwitch: (TO_HOT, TO_COLD),
    caps.Compressor: (TURN_ON, TURN_OFF),
    caps.SpectrumAnalyzer: (CONFIGURE_SPECTRUM, READ_TRACE),
    caps.NetworkAnalyzer: (CONFIGURE_NETWORK, READ_TRACE),
}

# Chopper (driver and simulator): continuous rotation, the load stays undefined
START_ROTATION = Action(
    "start_rotation", "Continuous rotation",
    lambda t, frequency: t.start_rotation(frequency),
    arguments=(
        Argument("frequency", "Frequency", "Hz", default=10.0, minimum=0.1, maximum=20.0),
    ),
)  # fmt: skip
STOP_ROTATION = Action("stop", "Stop", lambda t: t.stop(), help="Stop the rotation")
CHOPPER_ACTIONS = (START_ROTATION, STOP_ROTATION)


def actions_for(
    capabilities: Iterable[type], extra: Iterable[Action] = ()
) -> List[Action]:
    """Actions of the given capabilities, then the extra (driver) ones."""
    return by_key(CAPABILITY_ACTIONS, capabilities, extra)


def actions_of(target: Any) -> List[Action]:
    """Actions of a device part: from its capabilities, then its own ones."""
    return actions_for(*declared(target, "actions"))
