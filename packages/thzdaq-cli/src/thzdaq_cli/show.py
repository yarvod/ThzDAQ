"""How answers are printed: aligned text for people, JSON for scripts."""

from typing import Any, Iterable, Optional, Sequence

import msgspec


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
