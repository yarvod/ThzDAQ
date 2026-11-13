"""Each concept is written once (AGENTS.md, «Architecture Rules»).

Across the source of all packages, these fail:
- two functions with the same body (three statements or more);
- the same phrase shown to people (two words or more) in two modules;
- the same dotted or slashed identifier (a procedure name, a settings key, a
  driver id) in two modules.

Put the shared thing in the module that owns it and import it. A phrase that only
looks the same, two concepts in two layers, goes into ALLOWED with the reason; an
entry that no longer repeats must leave ALLOWED, so the list only shrinks.
"""

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
# Scripts a person copies and makes theirs (examples of the bench's own
# measurements): package data written as a person writes, not modules of the
# program that could import what they name
EXAMPLES = ROOT / "packages/thzdaq-api/src/thzdaq_api/examples"
SOURCES = sorted(
    path
    for path in ROOT.glob("packages/*/src/**/*.py")
    if not path.is_relative_to(EXAMPLES)
)

ALLOWED = {
    "Voltage setpoint": "a column title of measurement files (data) and the label "
    "of an instrument quantity (instruments): each layer names its own things",
    "Coil current": "a column title of measurement files and the label of the "
    "I-CL sweep parameter",
    "Traceback (most recent call last):": "Python's own words, not ours: the daemon "
    "finds the error a script's process printed, the window the one its output "
    "shows to mend; neither may import the other",
}

# Identifiers two packages that may not import each other both need
ALLOWED_IDENTIFIERS = {
    "application/json": "the JSON media type: instruments speak HTTP to devices, "
    "the contract to its clients, and neither may import the other",
    "text/plain": "the plain text media type: a Jupyter kernel's results to the "
    "window's console, an MCP resource to an agent; clients do not import each other",
}

IDENTIFIER = re.compile(r"[A-Za-z][\w.\-]*[./][\w.\-/]*\w")


def module_of(path: Path) -> str:
    return path.relative_to(ROOT).as_posix().split("/src/", 1)[1]


def docstrings(tree: ast.AST) -> Set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def scan():
    phrases: Dict[str, Set[str]] = defaultdict(set)
    identifiers: Dict[str, Set[str]] = defaultdict(set)
    bodies: Dict[str, List[str]] = defaultdict(list)
    for path in SOURCES:
        module = module_of(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = docstrings(tree) | {
            id(part)
            for node in ast.walk(tree)
            if isinstance(node, ast.JoinedStr)
            for part in node.values
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                if id(node) in skip or "\n" in text:
                    continue
                if IDENTIFIER.fullmatch(text) and not text.startswith("http"):
                    identifiers[text].add(module)
                elif len(text.split()) >= 2 and len(text) >= 6:
                    phrases[text].add(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if body and id(getattr(body[0], "value", None)) in skip:
                    body = body[1:]
                if len(body) >= 3:
                    dump = ast.dump(ast.Module(body=body, type_ignores=[]))
                    bodies[dump].append(f"{module}::{node.name}")
    return phrases, identifiers, bodies


PHRASES, IDENTIFIERS, BODIES = scan()


def repeated(found: Dict[str, Set[str]]) -> Dict[str, List[str]]:
    return {text: sorted(mods) for text, mods in found.items() if len(mods) > 1}


def test_no_function_is_written_twice():
    twice = [names for names in BODIES.values() if len(names) > 1]
    assert not twice, f"same body: {twice}"


def test_no_phrase_is_written_in_two_modules():
    found = {k: v for k, v in repeated(PHRASES).items() if k not in ALLOWED}
    assert not found, f"same phrase in several modules: {found}"


def test_no_identifier_is_written_in_two_modules():
    found = {
        k: v for k, v in repeated(IDENTIFIERS).items() if k not in ALLOWED_IDENTIFIERS
    }
    assert not found, f"same identifier in several modules: {found}"


def test_allowed_phrases_still_repeat():
    stale = [text for text in ALLOWED if text not in repeated(PHRASES)]
    stale += [text for text in ALLOWED_IDENTIFIERS if text not in repeated(IDENTIFIERS)]
    assert not stale, f"no longer repeated, remove from ALLOWED: {stale}"
