"""The bench's own measurements (Custom): a script with declarations at its top,
kept in the bench's library (measurements/ of the program's folder, next to
stations/) and listed among the procedures as custom.<its file name>.

    from thzdaq import connect, device, plot, value

    bias = device("SIS bias", kind="sis_bias")              # a slot of the form
    detector = device("Detector", "PowerDetector")
    voltage = value("Bias voltage", "0:7:351", unit="mV")   # a parameter
    t_hot, t_cold = value("Hot load", 300, unit="K"), value("Cold load", 77, unit="K")
    pv = plot("P-V", table="pv", x="voltage", y="power", group_by="load")

    lab = connect()
    with lab.measurement("pv_hot_cold", devices=[bias, detector]) as m:
        ...

A declaration is named by the name it is assigned to (bias, voltage): the
slots and parameters of the procedure, as thzdaq run custom.x --device
bias=sis_bias_2 --set voltage=0:7:101 names them. Declarations come first,
each assigned to a name, before connect().

The daemon learns a file's form by running it described (DESCRIBE_ENV: its
declarations are written to that file, and connect() ends the script before
it touches the bench), and runs it with the devices and values chosen
(INPUTS_ENV, values in SI as the daemon parsed them). Run as it is (python
x.py), a script takes the defaults, parsed by the daemon.
"""

import ast
from typing import Any, Dict, List, Optional, Tuple

import msgspec

from thzdaq_api.measurements import PlotInfo
from thzdaq_api.operation import Operation

GROUP = "custom"  # custom.<name>: the group of the bench's own measurements
LIBRARY = "measurements"  # the folder of the program that holds them
SUFFIX = ".py"
DESCRIBE_ENV = "THZDAQ_DESCRIBE"  # the file a described script writes into
INPUTS_ENV = "THZDAQ_INPUTS"  # the devices and values a run was given (JSON)
MODULE = "thzdaq"  # what a script imports declarations from

# Declarations by the function that makes them
DEVICE, VALUE, PLOT = "device", "value", "plot"
DECLARATIONS = (DEVICE, VALUE, PLOT)
CONNECT = "connect"  # declarations come before it

# Kinds of values, by their default (and choices)
FLOAT, INT, BOOL, CHOICE, SWEEP, TEXT = (
    "float",
    "int",
    "bool",
    "choice",
    "sweep",
    "text",
)
FLOAT_LIST, TEXT_LIST = "float_list", "string_list"


def procedure_name(name: str) -> str:
    """pv_hot_cold -> custom.pv_hot_cold"""
    return f"{GROUP}.{name}"


def file_name(procedure: str) -> Optional[str]:
    """custom.pv_hot_cold -> pv_hot_cold; None for another procedure."""
    group, dot, name = procedure.partition(".")
    return name if group == GROUP and dot and name else None


class SlotDeclared(msgspec.Struct, frozen=True):
    """device(title, *capabilities, kind=...): a device chosen in the form."""

    name: str
    title: str
    capabilities: Tuple[str, ...] = ()
    kind: Optional[str] = None


class ValueDeclared(msgspec.Struct, frozen=True):
    """value(title, default, unit=...): a parameter, its default and limits as
    people type them (in unit; a sweep "start:stop:points")."""

    name: str
    title: str
    default: Any
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[Any, ...] = ()
    help: str = ""


class Declarations(msgspec.Struct, frozen=True):
    """What a script declares at its top, in order."""

    slots: Tuple[SlotDeclared, ...] = ()
    values: Tuple[ValueDeclared, ...] = ()
    plots: Tuple[PlotInfo, ...] = ()


class Given(msgspec.Struct, frozen=True):
    """A value a script is given: SI as JSON carries it (a sweep {start, stop,
    points}), its SI unit and its kind."""

    value: Any
    unit: str = ""
    kind: str = FLOAT


class Inputs(msgspec.Struct, frozen=True):
    """What a run of a custom measurement was given: a device per slot, a
    value per parameter, by their names."""

    devices: Dict[str, str] = {}
    values: Dict[str, Given] = {}


class ParseValue(Operation[Given]):
    """A declared value's default as people type it (in its unit; a sweep
    "start:stop:points"), parsed as a run of the measurement takes it: SI,
    with its SI unit and kind. Invalid ones are refused."""

    value: ValueDeclared


class DeclarationError(ValueError):
    """Declarations a script cannot be described by: told with the line."""


def _called(node: ast.AST, names: Dict[str, str]) -> Optional[str]:
    """The declaration (or connect) a call makes, by the names the script
    imported them as; None for another call."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return names.get(func.id)
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and names.get(func.value.id) == MODULE
    ):
        return func.attr if func.attr in (*DECLARATIONS, CONNECT) else None
    return None


def _imported(tree: ast.Module) -> Dict[str, str]:
    """Names in the script -> the declaration, connect or the module they are."""
    found: Dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == MODULE or node.module.startswith("thzdaq_api"))
        ):
            for alias in node.names:
                if alias.name == "*":
                    found.update((name, name) for name in (*DECLARATIONS, CONNECT))
                elif alias.name in (*DECLARATIONS, CONNECT):
                    found[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == MODULE:
                    found[alias.asname or alias.name] = MODULE
    return found


def declared_names(text: str) -> Tuple[Tuple[str, str], ...]:
    """(declaration, name) of each declaration a script's text makes, in
    order. DeclarationError for one not assigned to a name, or one after
    connect(); SyntaxError for text that is no Python."""
    tree = ast.parse(text)
    names = _imported(tree)
    found: List[Tuple[str, str]] = []
    connected: Optional[int] = None
    for statement in tree.body:
        targets: List[Tuple[ast.AST, ast.AST]] = []
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, assigned = statement.targets[0], statement.value
            if isinstance(target, ast.Tuple) and isinstance(assigned, ast.Tuple):
                targets = list(zip(target.elts, assigned.elts))
            else:
                targets = [(target, assigned)]
        for node in ast.walk(statement):
            made = _called(node, names)
            if made is None:
                continue
            if made == CONNECT:
                connected = connected or node.lineno
                continue
            if connected is not None:
                raise DeclarationError(
                    f"line {node.lineno}: {made}(...) after connect() on line"
                    f" {connected}: declare before connect()"
                )
            name = next(
                (t.id for t, v in targets if v is node and isinstance(t, ast.Name)),
                None,
            )
            if name is None:
                raise DeclarationError(
                    f"line {node.lineno}: assign {made}(...) to a name at the"
                    f" top of the file: x = {made}(...)"
                )
            found.append((made, name))
    return tuple(found)


def title_of(text: str, name: str) -> Tuple[str, str]:
    """A script's title and what it does: the first line of its docstring and
    the rest; its file's name and nothing without one."""
    try:
        doc = ast.get_docstring(ast.parse(text)) or ""
    except SyntaxError:
        doc = ""
    title, _, about = doc.partition("\n")
    return title.strip() or name, about.strip()
