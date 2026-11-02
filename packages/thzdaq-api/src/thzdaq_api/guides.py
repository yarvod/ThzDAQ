"""Guides for agents and the assistant: how to work with the bench, as text a
model reads (thzdaq://guide/<topic> of the MCP server, AGENTS.md of a
workspace). They are files of this package, so every installation has them:
the build, a PyPI install and the sources."""

from importlib import resources
from importlib.resources.abc import Traversable
from typing import Tuple

from thzdaq_api.errors import ErrorCode, LabError

FOLDER = "assistant"
SUFFIX = ".md"
AGENTS = "agents"  # how an agent measures with the bench: the AGENTS.md of a workspace


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
