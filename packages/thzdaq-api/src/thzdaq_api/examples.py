"""Examples of the bench's own measurements: files of this package
(examples/), each a script with declarations (thzdaq_api.custom) that runs as
it is on the simulators of the example profile; a person copies one into the
library (measurements/) and makes it theirs. The first line of its docstring
is its title, the rest says what it does. They are files of the package, so
every installation has them: the build, a PyPI install and the sources."""

import ast
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Tuple

import msgspec

from thzdaq_api.errors import ErrorCode, LabError

FOLDER = "examples"
SUFFIX = ".py"


class Example(msgspec.Struct, frozen=True):
    name: str  # its file without the suffix: the name a new script gets
    title: str
    about: str  # what it does
    text: str


def folder() -> Traversable:
    return resources.files(__package__) / FOLDER


def read(item: Traversable) -> Example:
    text = item.read_text(encoding="utf-8")
    title, _, about = (ast.get_docstring(ast.parse(text)) or "").partition("\n")
    return Example(item.name.removesuffix(SUFFIX), title, about.strip(), text)


def examples() -> Tuple[Example, ...]:
    """Every example, by name."""
    found = [read(item) for item in folder().iterdir() if item.name.endswith(SUFFIX)]
    return tuple(sorted(found, key=lambda t: t.name))


def example(name: str) -> Example:
    """LabError NOT_FOUND names the examples there are."""
    for found in examples():
        if found.name == name:
            return found
    raise LabError(
        ErrorCode.NOT_FOUND,
        f"No example {name!r}",
        f"known: {', '.join(e.name for e in examples())}",
    )


def write_new(folder: Path, name: str, text: str) -> Path:
    """text as a new script folder/name.py, or name_2.py, name_3.py, ... when
    that is taken: never over a file there."""
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        path = folder / (
            f"{name}{SUFFIX}" if number == 1 else f"{name}_{number}{SUFFIX}"
        )
        try:
            # newline="": the text as it is, line ends too (a kept script's
            # hash stays its own)
            with open(path, "x", encoding="utf-8", newline="") as file:
                file.write(text)
            return path
        except FileExistsError:
            number += 1


def create(name: str, folder: Path) -> Path:
    """A new script from the example name in folder, under its name."""
    found = example(name)
    return write_new(folder, found.name, found.text)
