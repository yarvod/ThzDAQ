"""Guides for agents and the assistant: how to work with the bench, as text a
model reads (thzdaq://guide/<topic> of the MCP server, AGENTS.md of a
workspace, the system prompt of the assistant in the window). They are files
of this package, so every installation has them: the build, a PyPI install and
the sources. The rules are written once, in the agents' guide; the assistant
reads them as a section of it."""

from importlib import resources
from importlib.resources.abc import Traversable
from typing import Tuple

from thzdaq_api.errors import ErrorCode, LabError

FOLDER = "assistant"
SUFFIX = ".md"
AGENTS = "agents"  # how an agent measures with the bench: the AGENTS.md of a workspace
ASSISTANT = "assistant"  # the assistant in the window: its part of the system prompt
# Sections of the agents' guide the assistant reads too
RULES = "Rules"
OWN_MEASUREMENT = "A measurement of the bench's own"


def folder() -> Traversable:
    return resources.files(__package__) / FOLDER


def topics() -> Tuple[str, ...]:
    return tuple(
        sorted(
            item.name.removesuffix(SUFFIX)
            for item in folder().iterdir()
            if item.name.endswith(SUFFIX)
        )
    )


def guide(topic: str) -> str:
    """The guide's text (Markdown); LabError NOT_FOUND names the topics."""
    if topic not in topics():
        raise LabError(
            ErrorCode.NOT_FOUND,
            f"No guide {topic!r}",
            f"known: {', '.join(topics())}",
        )
    return (folder() / f"{topic}{SUFFIX}").read_text(encoding="utf-8")


def section(topic: str, heading: str) -> str:
    """One section of a guide (## heading), with its heading, up to the next
    one; LabError NOT_FOUND when the guide has none so named."""
    lines = guide(topic).splitlines()
    head = f"## {heading}"
    if head not in lines:
        raise LabError(ErrorCode.NOT_FOUND, f"No section {heading!r} in {topic}")
    start = lines.index(head)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()
