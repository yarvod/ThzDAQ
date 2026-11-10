"""An instrument a script declares (instrument(...) of thzdaq), its raw
commands named as values: reading(...) asks the instrument and makes a value
of its answer (a number in SI with its unit and the quantity it came from, as
a device's reading is), setting(...) besides writes one, checked first
against the limits the script gives.

    gauge = instrument("gauge_1", driver="generic.scpi",
        connection="tcp://169.254.0.50:5025",
        pressure=reading("PR1?", unit="Pa", parse=r"P=([0-9.Ee+-]+)", scale=100),
        setpoint=setting("VOLT?", "VOLT {:.6f}", unit="V", minimum=0, maximum=5),
    )
    gauge.pressure          # P=1.2E+00 (mbar) -> 120.0 Pa
    gauge.setpoint = 2.5    # VOLT 2.500000, a raw write
    gauge.raw("*IDN?")      # any command as typed

Only the script knows these names: the daemon, the instrument's dock and
agents see its raw commands. A raw write waits for a person, unless the
script was started with --allow raw:<instrument>; within a measurement (with
lab.measurement) the person's yes to the first one holds until it ends. The
limits guard against a wrong value (25 for 2.5), not the bench: the script
may change them.

parse says how an answer becomes a value: None a number ("2.500"); a regular
expression the number its first group matches (r"P=([0-9.Ee+-]+)"); a dict
of answers and the values they mean ({"ON": True, "OFF": False}), which a
setting writes back as the answer; a function of the answer, for anything
else. scale multiplies a number read (and divides one written): mbar -> Pa
is scale=100, so that unit is SI.
"""

import re
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Union

from thzdaq_api.data import Measured
from thzdaq_api.devices import shown
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lab import Bench, Device, Readout
from thzdaq_api.procedures import entry

Parse = Union[None, str, Mapping[str, Any], Callable[[str], Any]]


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Reading:
    """A value the instrument answers a raw query with."""

    def __init__(
        self,
        query: Optional[str],
        unit: str = "",
        parse: Parse = None,
        scale: float = 1.0,
        title: str = "",
    ):
        self.query = query
        self.unit = unit
        self.parse = parse
        self.scale = scale
        self.title = title

    def value(self, answer: str, source: str) -> Any:
        """The answer as the script uses it: a number scaled, with its unit
        and source (Measured); another value as parse makes it."""
        found = self._parsed(answer.strip(), source)
        if not _number(found):
            return found
        return Measured(found * self.scale, self.unit, self.title, source)

    def _parsed(self, answer: str, source: str) -> Any:
        parse = self.parse
        try:
            if callable(parse):
                return parse(answer)
            if isinstance(parse, Mapping):
                return parse[_key(parse, answer)]
            if isinstance(parse, str):
                found = re.search(parse, answer)
                if found is None:
                    raise ValueError(f"{parse!r} finds nothing")
                return float(found.group(1) if found.re.groups else found.group(0))
            return float(answer)
        except (ValueError, KeyError, TypeError) as e:
            raise LabError(
                ErrorCode.INSTRUMENT,
                f"{source}: the answer {answer!r} to {self.query!r} reads as no"
                f" value ({e})",
                "parse= of reading(...) says how to read it: a regular"
                " expression, a dict of answers, a function",
            ) from None

    def __repr__(self) -> str:
        return f"reading({self.query!r}, unit={self.unit!r})"


def _key(answers: Mapping[str, Any], answer: str) -> str:
    """The key of a dict parse the answer is: as written, else in any case."""
    if answer in answers:
        return answer
    for key in answers:
        if key.lower() == answer.lower():
            return key
    raise KeyError(f"not one of {', '.join(map(repr, answers))}")


class Setting(Reading):
    """A value written to the instrument by a raw command; read back with
    its query, when it has one."""

    def __init__(
        self,
        query: Optional[str],
        write: str,
        unit: str = "",
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
        parse: Parse = None,
        scale: float = 1.0,
        title: str = "",
    ):
        super().__init__(query, unit, parse, scale, title)
        self.write = write
        self.minimum = minimum
        self.maximum = maximum

    def command(self, value: Any, source: str) -> str:
        """The raw command that writes the value, once it is within the
        limits: a number divided by scale, a value of a dict parse as its
        answer."""
        if isinstance(self.parse, Mapping):
            answers = [key for key, meant in self.parse.items() if meant == value]
            if not answers:
                raise LabError(
                    ErrorCode.INVALID_ARGUMENTS,
                    f"{source}: {value!r} is none of"
                    f" {', '.join(map(repr, self.parse.values()))}",
                )
            return self.write.format(answers[0])
        if not _number(value):
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"{source}: {value!r} is no number",
                f"give it in {self.unit or 'its unit'}, as a number",
            )
        low, high = self.minimum, self.maximum
        if (low is not None and value < low) or (high is not None and value > high):
            limits = f"{'' if low is None else f'{low:g}'}..{'' if high is None else f'{high:g}'}"
            raise LabError(
                ErrorCode.OUT_OF_LIMITS,
                f"{source}: {float(value):g} {self.unit} is beyond {limits}"
                f" {self.unit}".rstrip(),
                "minimum= and maximum= of setting(...) bound it",
            )
        return self.write.format(float(value) / self.scale)

    def __repr__(self) -> str:
        return f"setting({self.query!r}, {self.write!r}, unit={self.unit!r})"


def reading(
    query: str,
    unit: str = "",
    parse: Parse = None,
    scale: float = 1.0,
    title: str = "",
) -> Reading:
    """A value the instrument answers query with (a raw command, "PR1?"):
    parsed by parse, multiplied by scale, in unit (SI)."""
    return Reading(query, unit, parse, scale, title)


def setting(
    query: Optional[str],
    write: str,
    unit: str = "",
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    parse: Parse = None,
    scale: float = 1.0,
    title: str = "",
) -> Setting:
    """A value written by write ("VOLT {:.6f}": the value divided by scale
    goes into its braces) and read back by query (None: written only).
    minimum and maximum (in unit) bound what is written."""
    return Setting(query, write, unit, minimum, maximum, parse, scale, title)


class RawInstrument(Device):
    """An instrument of the profile as a script declared it: its device (its
    own quantities and actions, none for a generic driver), the values the
    script named its raw commands by, and raw(command) for any other."""

    def __init__(self, bench: Bench, ref: str, named: Mapping[str, Reading]):
        super().__init__(bench, ref)
        object.__setattr__(self, "named", dict(named))

    def raw(self, command: str, answer: bool = False) -> Optional[str]:
        """A command as typed (lab.raw): the answer of a query (with ?), or
        of a write with answer."""
        return self.bench.raw(self.ref, command, answer)

    def _get(self, name: str) -> Any:
        found = self.named[name]
        source = entry(self.ref, name)
        if found.query is None:
            raise LabError(
                ErrorCode.NOT_ALLOWED,
                f"{source} is only written",
                "give setting(...) a query to read it back",
            )
        return found.value(self.bench.raw(self.ref, found.query, True), source)

    def _set(self, name: str, value: Any) -> None:
        found = self.named[name]
        if not isinstance(found, Setting):
            raise LabError(
                ErrorCode.NOT_ALLOWED,
                f"{entry(self.ref, name)} is only read",
                "declare it with setting(...) to write it",
            )
        self.bench.raw(self.ref, found.command(value, entry(self.ref, name)))

    def read(self, *keys: str, display: bool = False) -> Readout:
        """What it reads: its own quantities and the readings named, or the
        keys of them."""
        named = [key for key in keys if key in self.named] if keys else list(self.named)
        own = [key for key in keys if key not in self.named]
        found = (
            Readout(super().read(*own, display=display))
            if own or not keys
            else Readout()
        )
        for key in named:
            if self.named[key].query is not None:
                value = self._get(key)
                found[key] = shown(value, self.named[key].unit) if display else value
        return found

    def __getattr__(self, name: str) -> Any:
        if name in self.named:
            return self._get(name)
        return super().__getattr__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.named:
            self._set(name, value)
        else:
            super().__setattr__(name, value)

    def __setitem__(self, key: str, value: Any) -> None:
        self.__setattr__(key, value)

    def __dir__(self) -> Iterable[str]:
        return [*self.named, *super().__dir__(), "raw"]

    def __repr__(self) -> str:
        return f"<instrument {self.ref}>"


def named_values(quantities: Dict[str, Any]) -> Dict[str, Reading]:
    """What instrument(...) was given besides its id, driver and
    connection: readings and settings only."""
    wrong = [
        name for name, given in quantities.items() if not isinstance(given, Reading)
    ]
    if wrong:
        raise TypeError(
            f"{', '.join(wrong)}: give an instrument reading(...) or setting(...)"
        )
    return dict(quantities)
