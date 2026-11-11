"""What an agent reads without calling a tool: the procedures, the profile, and
the guides of thzdaq_api (thzdaq://guide/agents)."""

from typing import Any, Awaitable, Callable, Dict, List, Tuple
from urllib.parse import urlsplit

import mcp_types as types
import msgspec
from thzdaq_api import guides
from thzdaq_api.devices import ListDevices
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import DescribeProcedure, ListProcedures
from thzdaq_api.station import CONNECTION, INSTRUMENTS, KIND, GetStation

from thzdaq_mcp import present
from thzdaq_mcp.bench import Bench

SCHEME = "thzdaq"
PROCEDURES = "procedures"
STATION = "station"
GUIDE = "guide"
TEXT = "text/plain"
MARKDOWN = "text/markdown"
JSON = "application/json"

Content = Tuple[str, str]  # (MIME type, text)


def address(*parts: str) -> str:
    """thzdaq://procedures/sis.current_vs_voltage"""
    return f"{SCHEME}://" + "/".join(parts)


def listed() -> List[types.Resource]:
    return [
        types.Resource(
            name=PROCEDURES,
            uri=address(PROCEDURES),
            description="What the bench measures: every procedure",
            mime_type=TEXT,
        ),
        types.Resource(
            name=STATION,
            uri=address(STATION),
            description="The bench's profile: instruments, their devices, limits "
            "and safe state (connections by their kind only)",
            mime_type=JSON,
        ),
        *(
            types.Resource(
                name=f"{GUIDE} {topic}", uri=address(GUIDE, topic), mime_type=MARKDOWN
            )
            for topic in guides.topics()
        ),
    ]


def templates() -> List[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(
            name="procedure",
            uri_template=address(PROCEDURES, "{name}"),
            description="A procedure: parameters in the units they are typed in, "
            "the devices that suit each slot, its plots",
            mime_type=TEXT,
        ),
        types.ResourceTemplate(
            name=GUIDE,
            uri_template=address(GUIDE, "{topic}"),
            description="How to work with the bench: " + ", ".join(guides.topics()),
            mime_type=MARKDOWN,
        ),
    ]


def without_addresses(profile: Dict[str, Any]) -> Dict[str, Any]:
    """The profile as an agent reads it: a connection only by its kind, no
    host, port or anything a device is reached with."""
    instruments = {
        name: {**instrument, CONNECTION: {KIND: instrument[CONNECTION].get(KIND)}}
        if CONNECTION in instrument
        else instrument
        for name, instrument in profile.get(INSTRUMENTS, {}).items()
    }
    return {**profile, INSTRUMENTS: instruments}


async def procedures(bench: Bench, name: str) -> Content:
    if not name:
        return TEXT, present.procedures(await bench.call(ListProcedures()))
    info = await bench.call(DescribeProcedure(procedure=name))
    return TEXT, present.procedure(info, await bench.call(ListDevices()))


async def station(bench: Bench, name: str) -> Content:
    profile = await bench.call(GetStation())
    shown = {"name": profile.name, "simulate": profile.simulate,
             "profile": without_addresses(profile.profile)}  # fmt: skip
    return JSON, msgspec.json.format(msgspec.json.encode(shown)).decode()


async def guide(bench: Bench, topic: str) -> Content:
    return MARKDOWN, guides.guide(topic)


READERS: Dict[str, Callable[[Bench, str], Awaitable[Content]]] = {
    PROCEDURES: procedures,
    STATION: station,
    GUIDE: guide,
}


async def read(bench: Bench, uri: str) -> Content:
    """LabError NOT_FOUND for an address that is none of these."""
    parts = urlsplit(uri)
    reader = READERS.get(parts.netloc) if parts.scheme == SCHEME else None
    if reader is None:
        raise LabError(
            ErrorCode.NOT_FOUND,
            f"No resource {uri}",
            f"known: {', '.join(address(name) for name in READERS)}",
        )
    return await reader(bench, parts.path.strip("/"))
