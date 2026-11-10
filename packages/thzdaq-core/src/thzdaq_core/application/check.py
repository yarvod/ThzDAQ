"""A script of the bench's own measurements checked before it runs: its syntax,
undefined and unused names (pyflakes), its declarations (the form it
describes), and what it names of this bench, read from its text:

- devices named lab["ref"] the bench has not;
- a slot (device(...)) no device of the bench suits;
- an instrument (instrument(...)) the profile has not, or has with another
  driver: its first run asks a person to put it there;
- a quantity or action after a device's dot it has not (bias.voltge);
- a sweep (for v in m.sweep(...): bias.voltage_set = v) beyond the limits of
  the quantity it sets, by the default of a declared value or a typed text.

What a script does at run time no check can know: this one tells what its
text shows.
"""

import ast
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple, Type

from pyflakes import api as flakes
from thzdaq_api.custom import (
    BENCH,
    DECLARED,
    NAMES,
    SYNTAX,
    CustomCheck,
    DeclarationError,
    Problem,
    ValueDeclared,
    declared_names,
)
from thzdaq_api.devices import DeviceInfo, QuantityInfo
from thzdaq_api.lab import Device
from thzdaq_api.measurements import SlotInfo

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.custom import CustomMeasurements
from thzdaq_core.application.describe import (
    device_info,
    procedure_info,
    quantity_info,
)
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.custom import CustomProcedure, parameter
from thzdaq_core.domain.parameters import Sweep

SWEEP = "sweep"  # the session's method that sweeps
UNIT = "unit"
# What a device object has besides its quantities and actions
OF_DEVICE = {name for name in vars(Device) if not name.startswith("_")} | {
    "bench",
    "ref",
}


class Flakes:
    """pyflakes' reporter: what it finds, as problems."""

    def __init__(self):
        self.found: List[Problem] = []

    def flake(self, message) -> None:
        text = message.message % message.message_args
        self.found.append(Problem(message.lineno, text, NAMES))

    def syntaxError(self, filename, message, line, offset, text) -> None:
        self.found.append(Problem(line, message, SYNTAX))

    def unexpectedError(self, filename, message) -> None:
        self.found.append(Problem(None, message, SYNTAX))


@dataclass
class BenchView:
    """What the check reads of the bench: its devices, and of each what it
    reads, takes (with the limits) and does."""

    devices: Tuple[DeviceInfo, ...]
    quantities: Dict[str, Tuple[QuantityInfo, ...]] = field(default_factory=dict)
    actions: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    def refs(self) -> Tuple[str, ...]:
        return tuple(device.ref for device in self.devices)

    def has(self, ref: str, name: str) -> bool:
        keys = {q.key for q in self.quantities.get(ref, ())}
        return name in keys or name in self.actions.get(ref, ())

    def quantity(self, ref: str, key: str) -> Optional[QuantityInfo]:
        return next((q for q in self.quantities.get(ref, ()) if q.key == key), None)


def bench_view(bench: Bench, access: DeviceAccess) -> BenchView:
    station = bench.station
    devices = tuple(device_info(info, station) for info in station.devices())
    view = BenchView(devices)
    for device in devices:
        guard = station.guard(device.ref)
        view.quantities[device.ref] = tuple(
            quantity_info(q, guard) for q in access.quantities(device.ref)
        )
        view.actions[device.ref] = tuple(a.key for a in access.actions(device.ref))
    return view


def _text(node: ast.AST) -> Optional[str]:
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


class TextOfBench:
    """The devices a script's text names, and what it does with them."""

    def __init__(
        self,
        tree: ast.Module,
        view: BenchView,
        procedure: Optional[Type[CustomProcedure]],
    ):
        self.tree = tree
        self.view = view
        self.procedure = procedure
        self.problems: List[Problem] = []
        self.devices: Dict[str, Tuple[str, ...]] = {}  # variable -> its devices
        self.values: Dict[str, ValueDeclared] = {}  # variable -> declared value

    def check(self) -> List[Problem]:
        self._declared()
        self._named()
        self._attributes()
        self._sweeps()
        return self.problems

    def _declared(self) -> None:
        """Slots and values the script declares, by their variables."""
        if self.procedure is None:
            return
        declarations = self.procedure.declarations
        for slot in declarations.slots:
            info = SlotInfo(slot.name, slot.title, slot.capabilities, slot.kind)
            suitable = tuple(d.ref for d in info.candidates(self.view.devices))
            self.devices[slot.name] = suitable
            if not suitable:
                self.problems.append(
                    Problem(
                        self._line_of(slot.name),
                        f"no device of this bench suits {slot.name} ({slot.title})",
                        BENCH,
                    )
                )
        self.values = {value.name: value for value in declarations.values}
        drivers = {d.ref: d.driver for d in self.view.devices if d.ref == d.instrument}
        for declared in declarations.instruments:
            found = drivers.get(declared.instrument)
            if found == declared.driver:
                continue
            told = (
                "is not in the profile"
                if found is None
                else f"is in the profile with {found}"
            )
            self.problems.append(
                Problem(
                    self._line_of(declared.name),
                    f"{declared.instrument} {told}: the first run asks a person"
                    f" to put it there with {declared.driver}",
                    BENCH,
                )
            )

    def _line_of(self, name: str) -> Optional[int]:
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            ):
                return node.lineno
        return None

    def _named(self) -> None:
        """lab["ref"]: a device of the bench; one assigned to a name is that
        name's."""
        known = set(self.view.refs())
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Subscript):
                ref = _text(node.slice)
                if ref is not None and isinstance(node.value, ast.Name):
                    if ref not in known:
                        self.problems.append(
                            Problem(
                                node.lineno, f"no device {ref!r} on this bench", BENCH
                            )
                        )
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Subscript)
                and isinstance(node.value.value, ast.Name)
            ):
                ref = _text(node.value.slice)
                if ref in known:
                    self.devices[node.targets[0].id] = (ref,)

    def _attributes(self) -> None:
        """device.name: a quantity or an action of every device it may be."""
        for node in ast.walk(self.tree):
            if not (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in self.devices
                and node.attr not in OF_DEVICE
            ):
                continue
            refs = self.devices[node.value.id]
            lacking = [ref for ref in refs if not self.view.has(ref, node.attr)]
            if lacking:
                self.problems.append(
                    Problem(
                        node.lineno,
                        f"{', '.join(lacking)} has no quantity or action {node.attr!r}",
                        BENCH,
                    )
                )

    def _sweeps(self) -> None:
        """for v in m.sweep(...): device.key = v — the sweep within the
        limits of what it sets."""
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
                continue
            swept = self._swept(node.iter)
            if swept is None:
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Assign)
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == node.target.id
                ):
                    for target in inner.targets:
                        self._within(target, swept, node.lineno)

    def _swept(self, called: ast.AST) -> Optional[Sweep]:
        """The sweep a call m.sweep(...) goes over, as its text tells."""
        if not (
            isinstance(called, ast.Call)
            and isinstance(called.func, ast.Attribute)
            and called.func.attr == SWEEP
            and called.args
        ):
            return None
        given = called.args[0]
        if isinstance(given, ast.Name) and given.id in self.values:
            declared = self.values[given.id]
        elif _text(given) is not None:
            unit = next((_text(k.value) for k in called.keywords if k.arg == UNIT), "")
            declared = ValueDeclared("", "", _text(given), unit or "")
        else:
            return None
        try:
            found = parameter(declared).default
        except ProcedureError:
            return None
        return found if isinstance(found, Sweep) else None

    def _within(self, target: ast.AST, swept: Sweep, line: int) -> None:
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id in self.devices
        ):
            return
        for ref in self.devices[target.value.id]:
            quantity = self.view.quantity(ref, target.attr)
            if quantity is None:
                continue
            low, high = sorted((swept.start, swept.stop))
            beyond = (quantity.minimum is not None and low < quantity.minimum) or (
                quantity.maximum is not None and high > quantity.maximum
            )
            if beyond:
                limits = "..".join(
                    "" if bound is None else f"{bound:g}"
                    for bound in (quantity.minimum, quantity.maximum)
                )
                self.problems.append(
                    Problem(
                        line,
                        f"{ref} · {quantity.title}: the sweep {swept.start:g}.."
                        f"{swept.stop:g} {quantity.unit} goes beyond {limits}"
                        f" {quantity.unit}",
                        BENCH,
                    )
                )


class Checks:
    def __init__(self, customs: CustomMeasurements, bench: Bench, access: DeviceAccess):
        self.customs = customs
        self.bench = bench
        self.access = access

    def check(self, name: str, text: Optional[str] = None) -> CustomCheck:
        """A script of the library as it is saved, or the text given."""
        if text is None:
            text = self.customs.text(name).text
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return CustomCheck(None, (Problem(e.lineno, e.msg or "", SYNTAX),))
        problems: List[Problem] = list(self._flakes(text, name))
        try:
            declared_names(text)
        except DeclarationError as e:
            return CustomCheck(
                None, tuple(problems + [Problem(e.line, str(e), DECLARED)])
            )
        found = self.customs.of_text(name, text)
        if found.procedure is None:
            problems.append(Problem(None, found.error, DECLARED))
        view = bench_view(self.bench, self.access)
        problems += TextOfBench(tree, view, found.procedure).check()
        info = None if found.procedure is None else procedure_info(found.procedure())
        return CustomCheck(info, tuple(sorted(problems, key=_order)))

    @staticmethod
    def _flakes(text: str, name: str) -> Iterable[Problem]:
        reporter = Flakes()
        flakes.check(text, f"{name}.py", reporter)
        return reporter.found


def _order(problem: Problem) -> Tuple[int, str]:
    return (problem.line or 0, problem.text)
