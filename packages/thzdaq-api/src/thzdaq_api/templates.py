"""Templates of new scripts: files of this package (script_templates/), each a
script that runs as it is on the simulators of the example profile; a person
copies one into a scripts folder and makes it theirs. The first line of its
docstring is its title, the rest says what it does. They are files of the
package, so every installation has them: the build, a PyPI install and the
sources."""

import ast
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Tuple

import msgspec

from thzdaq_api.errors import ErrorCode, LabError

FOLDER = "script_templates"
SUFFIX = ".py"


class Template(msgspec.Struct, frozen=True):
    name: str  # its file without the suffix: the name a new script gets
    title: str
    about: str  # what it does
    text: str


def folder() -> Traversable:
    return resources.files(__package__) / FOLDER


def read(item: Traversable) -> Template:
    text = item.read_text(encoding="utf-8")
    title, _, about = (ast.get_docstring(ast.parse(text)) or "").partition("\n")
    return Template(item.name.removesuffix(SUFFIX), title, about.strip(), text)


def templates() -> Tuple[Template, ...]:
    """Every template, by name."""
    found = [read(item) for item in folder().iterdir() if item.name.endswith(SUFFIX)]
    return tuple(sorted(found, key=lambda t: t.name))


def template(name: str) -> Template:
    """LabError NOT_FOUND names the templates there are."""
    for found in templates():
        if found.name == name:
            return found
    raise LabError(
        ErrorCode.NOT_FOUND,
        f"No script template {name!r}",
        f"known: {', '.join(t.name for t in templates())}",
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
    """A new script from the template name in folder, under its name."""
    found = template(name)
    return write_new(folder, found.name, found.text)
