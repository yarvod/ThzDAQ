"""What the script of this process declares at its top (thzdaq_api.declare) and
how it runs: described (the daemon learns its form), run by the daemon with
the devices and values chosen, or run as it is. A described script ends with
its last declaration (or at connect(), if it makes fewer than its text
does); connect() of a script whose declarations connected already returns
that bench.
"""

import atexit
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import msgspec

from thzdaq_api.custom import (
    DESCRIBE_ENV,
    INPUTS_ENV,
    DeclarationError,
    Declarations,
    Given,
    Inputs,
    InstrumentDeclared,
    SlotDeclared,
    ValueDeclared,
    declared_names,
)
from thzdaq_api.measurements import PlotInfo


def main_text() -> Optional[str]:
    """The text of the script this process runs; None without a file (a
    notebook, the interpreter's prompt)."""
    path = getattr(sys.modules["__main__"], "__file__", None)
    return Path(path).read_text(encoding="utf-8") if path else None


def slug(title: str) -> str:
    """ "Bias voltage" -> bias_voltage: a name where the text names none."""
    return re.sub(r"\W+", "_", title.strip().lower()).strip("_") or "value"


class Declaring:
    def __init__(
        self,
        describe: Optional[str] = None,
        inputs: Optional[Inputs] = None,
        text: Callable[[], Optional[str]] = main_text,
    ):
        """describe: the file the declarations are written into (the script
        is described); inputs: what a run by the daemon was given; text: the
        script's, which names the declarations (read at the first one)."""
        self.describe = describe
        self.inputs = inputs
        self.text = text
        self.slots: List[SlotDeclared] = []
        self.values: List[ValueDeclared] = []
        self.plots: List[PlotInfo] = []
        self.instruments: List[InstrumentDeclared] = []
        self.given: Dict[str, Given] = {}  # the values, as given or parsed
        self.bench: Any = None  # the bench the declarations connected to
        self._names: Optional[Tuple[Tuple[str, str], ...]] = None
        self._named = False  # a text names them
        if describe:
            atexit.register(self.write)  # a script that never connects

    @classmethod
    def of_process(cls) -> "Declaring":
        given = os.environ.get(INPUTS_ENV)
        return cls(
            os.environ.get(DESCRIBE_ENV) or None,
            msgspec.json.decode(given, type=Inputs) if given else None,
        )

    @property
    def describing(self) -> bool:
        return self.describe is not None

    def name(self, declaration: str, title: str, made: int) -> str:
        """The name of the declaration made as the made-th of its kind: the
        name the text assigns it to; without a text, one from its title."""
        if self._names is None:
            text = self.text()
            self._names = () if text is None else declared_names(text)
            self._named = text is not None
        if not self._named:
            return slug(title)
        names = [name for kind, name in self._names if kind == declaration]
        if made >= len(names):
            raise DeclarationError(
                f"{declaration}({title!r}) is not at the top of the file:"
                " declare each once, assigned to a name, before connect()"
            )
        return names[made]

    def declared(self) -> None:
        """After each declaration: a described script ends with its last one,
        before anything else it does."""
        made = sum(map(len, (self.slots, self.values, self.plots, self.instruments)))
        if self.describing and self._named and made >= len(self._names):
            self.described()

    def declarations(self) -> Declarations:
        return Declarations(
            tuple(self.slots),
            tuple(self.values),
            tuple(self.plots),
            tuple(self.instruments),
        )

    def write(self) -> None:
        """The declarations into the file the daemon reads."""
        if self.describe is not None:
            Path(self.describe).write_bytes(msgspec.json.encode(self.declarations()))

    def described(self) -> None:
        """A described script's form is known (its last declaration, or
        connect()): it ends before it touches the bench."""
        self.write()
        raise SystemExit(0)


STATE = Declaring.of_process()  # this process's script
