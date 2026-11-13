"""Code the assistant writes where the person types, without Qt: what the
model is asked and what of its answer goes into the text.

- write: Ctrl+I, code asked for in words, at the cursor or in place of the
  selection; the whole text with it comes back, a proposal to look at;
- ghost: what may follow the cursor, shown grey while typing;
- fix: a text that failed, with its error (and the console's last inputs),
  mended; the whole of it comes back, a proposal too.

The model is told the bench's devices and how its scripts are written (the
guide hints, and the agents' section on the bench's own measurements). It
answers with code alone, in a fenced block or bare.
"""

import re
from typing import List, Optional, Sequence

from thzdaq_api import guides

from thzdaq_gui.assistant.provider import Message

IN_FILE, IN_CONSOLE = "file", "console"  # where the code is
WHERE = {
    IN_FILE: "a script of the bench, open in the editor",
    IN_CONSOLE: (
        "the input of the window's Python console: `from thzdaq import *` and "
        "`lab = connect()` ran already, the code runs as the person enters it"
    ),
}
CURSOR = "<CURSOR>"
SELECTED, END_SELECTED = "<SELECTION>", "</SELECTION>"
DEVICES = "## The devices of the bench"
GHOST_LINES = 6  # lines of a ghost text at most
FENCED = re.compile(r"```[\w+-]*[ \t]*\n(.*?)(?:\n[ \t]*```|\Z)", re.DOTALL)


def system(devices: str) -> str:
    """The system prompt: the guide, how a script is written, the devices
    (one per line, as thzdaq_api.present lists them)."""
    return "\n\n".join(
        (
            guides.guide(guides.HINTS).strip(),
            guides.section(guides.AGENTS, guides.OWN_MEASUREMENT),
            f"{DEVICES}\n\n{devices}",
        )
    )


def _asked(system_prompt: str, content: str) -> List[Message]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]


def _shown(where: str, code: str) -> str:
    return f"This is {WHERE[where]}:\n```python\n{code}\n```"


def write_messages(
    system_prompt: str, where: str, code: str, start: int, end: int, asked: str
) -> List[Message]:
    """Ctrl+I: code for what is asked, at the cursor (start == end) or in
    place of the selection [start, end)."""
    if start == end:
        marked = code[:start] + CURSOR + code[end:]
        place = f"at {CURSOR}"
    else:
        marked = code[:start] + SELECTED + code[start:end] + END_SELECTED + code[end:]
        place = f"in place of what is between {SELECTED} and {END_SELECTED}"
    return _asked(
        system_prompt,
        f"{_shown(where, marked)}\n\nWrite the code that goes {place}: {asked}\n"
        "Answer with that code only, indented as it goes there.",
    )


def ghost_messages(
    system_prompt: str, where: str, code: str, cursor: int
) -> List[Message]:
    """What the person may type next at the cursor."""
    marked = code[:cursor] + CURSOR + code[cursor:]
    return _asked(
        system_prompt,
        f"{_shown(where, marked)}\n\nComplete the code at {CURSOR}: answer with what "
        f"follows it only, at most {GHOST_LINES} lines, nothing when nothing fits.",
    )


def fix_messages(
    system_prompt: str,
    where: str,
    code: str,
    error: str,
    recent: Sequence[str] = (),
) -> List[Message]:
    """The code that failed with its error; recent: inputs before it."""
    before = ""
    if recent:
        entered = "\n\n".join(recent)
        before = f"Entered before it, the oldest first:\n```python\n{entered}\n```\n\n"
    return _asked(
        system_prompt,
        f"{before}{_shown(where, code)}\n\nIt failed:\n```\n{error.strip()}\n```\n\n"
        "Fix it: answer with the whole code mended.",
    )


def code_of(answer: str) -> str:
    """The code of an answer: its first fenced block, else all of it; blank
    lines around it left out, the indent of its first line kept."""
    found = FENCED.search(answer)
    text = found[1] if found else answer
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(line.rstrip() for line in lines)


def written(code: str, start: int, end: int, answer: str) -> str:
    """The text with the code of the answer at the cursor or in place of the
    selection. Typed on a line with nothing before the cursor, the code
    takes whole lines: it comes indented, and what followed goes on a line
    of its own."""
    new = code_of(answer)
    line_start = code.rfind("\n", 0, start) + 1
    if not code[line_start:start].strip():
        start = line_start
        line_end = code.find("\n", end)
        rest = code[end : len(code) if line_end < 0 else line_end]
        if rest.strip():
            new += "\n"
    return code[:start] + new + code[end:]


def ghost_text(code: str, cursor: int, answer: str) -> Optional[str]:
    """What the ghost shows after the cursor; None when the answer adds
    nothing. A model that wrote the start of the line again has it cut."""
    found = FENCED.search(answer)
    text = (found[1] if found else answer).replace(CURSOR, "").rstrip()
    line = code[code.rfind("\n", 0, cursor) + 1 : cursor]
    if line and text.startswith(line):
        text = text[len(line) :]
    elif not line.strip() and text.startswith("\n"):
        text = text.lstrip("\n")
    shown = "\n".join(text.split("\n")[:GHOST_LINES])
    return shown if shown.strip() else None


def fixed(code: str, answer: str) -> str:
    """The mended code, ended as the code was."""
    new = code_of(answer)
    return new + "\n" if code.endswith("\n") and new else new
