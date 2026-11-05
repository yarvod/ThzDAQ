"""How answers are printed: aligned text for people, JSON for scripts."""

from typing import Any, Iterable, Optional, Sequence

import msgspec
from thzdaq_api.approvals import Answer, Approval
from thzdaq_api.scripts import RUNNING, ScriptInfo


NO_FILE = "no file"  # a profile, or a run, not kept in a file


def profile(name: str, path: Optional[str]) -> str:
    return f"{name} ({path or NO_FILE})"


def as_json(value: Any) -> str:
    return msgspec.json.encode(value).decode()


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Columns as wide as their widest text; empty when there are no rows."""
    rows = [[f"{cell}" for cell in row] for row in rows]
    if not rows:
        return ""
    widths = [max(len(text) for text in column) for column in zip(headers, *rows)]
    lines = [headers, *rows]
    return "\n".join(
        "  ".join(text.ljust(width) for text, width in zip(line, widths)).rstrip()
        for line in lines
    )


def value(found: Any, unit: str = "") -> str:
    """A value as the daemon gives it (SI, power in dBm), with its unit."""
    if found is None:
        return "--"
    if isinstance(found, bool):
        return "on" if found else "off"
    if isinstance(found, float):
        return f"{found:.6g} {unit}".strip()
    return f"{found} {unit}".strip()


def approval(asked: Approval) -> str:
    """What waits for a person, as the window's dialog shows it."""
    lines = [f"#{asked.id} {asked.origin}: {asked.title}", asked.text]
    if asked.warning:
        lines.append(f"warning: {asked.warning}")
    if asked.options:
        lines.append(f"options: {', '.join(asked.options)}")
    return "\n".join(lines)


def answer(id: int, given: Answer) -> str:
    """How what waited was answered."""
    verdict = "allowed" if given.allowed else "denied"
    words = f": {given.text}" if given.text else ""
    return f"#{id} {verdict} by {given.by}{words}"


def script(info: ScriptInfo) -> str:
    """A script the daemon runs or ran, in a line: how it stands."""
    ended = "" if info.status == RUNNING else f" (exit code {info.exit_code})"
    return f"script {info.id} {info.name}: {info.status}{ended}"


def output(id: int, text: str) -> str:
    """What a script printed, each line marked with its number."""
    return "\n".join(f"script {id} | {line}" for line in text.splitlines())
