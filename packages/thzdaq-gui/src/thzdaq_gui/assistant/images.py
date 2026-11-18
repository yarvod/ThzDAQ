"""Images of the assistant, without Qt: what an image's first bytes tell (its
type and size, header()), and the assistant's own tool generate_image, which
has the image model of its server make an image (provider.Client.generate)
and shows it to the person; the model reads only that it was shown, and how
large. It is offered only when the server has an image model.
"""

import re
import struct
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from thzdaq_gui.assistant.attachments import PNG
from thzdaq_gui.assistant.chat import Image
from thzdaq_gui.assistant.conversation import Running
from thzdaq_gui.assistant.provider import Client, ProviderError, tool

GENERATE = "generate_image"
DESCRIPTION = (
    "Make an image with the image model of your server and show it to the"
    " person in the chat; you do not see it, you read only that it was shown."
    " Describe in prompt all it shows; give size only when the person asks"
    " for one."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "description": "What the image shows, in detail"},
        "size": {
            "type": "string",
            "description": "Its width and height in pixels, as 1024x1024 (the"
            " sizes the image model makes); leave it out for the model's own",
        },
    },
    "required": ["prompt"],
}
SIZE = re.compile(r"\d+x\d+")
NAME_LETTERS = 80  # of the prompt, as the image's name
SHOWN = "shown to the person, {width}x{height}"
NOT_MADE = "The image was not made: {why}"
NO_PROMPT = "give prompt: what the image shows"
WRONG_SIZE = "give size as its width and height, as 1024x1024, or leave it out"
NOT_AN_IMAGE = "the server answered what is not an image"

PNG_SIGN = b"\x89PNG\r\n\x1a\n"
JPEG_SIGN = b"\xff\xd8"
GIFS = (b"GIF87a", b"GIF89a")
# JPEG markers of a frame's start (they hold its size); C4, C8, CC are others
FRAMES = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


@dataclass(frozen=True)
class Header:
    """What an image's first bytes tell: its MIME type and size in pixels."""

    mime: str
    width: int
    height: int


def header(data: bytes) -> Optional[Header]:
    """Of a PNG, JPEG, GIF or WebP image; None for anything else."""
    try:
        if data.startswith(PNG_SIGN) and data[12:16] == b"IHDR":
            return Header(PNG, *struct.unpack(">II", data[16:24]))
        if data[:6] in GIFS:
            return Header("image/gif", *struct.unpack("<HH", data[6:10]))
        if data.startswith(JPEG_SIGN):
            return _jpeg(data)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _webp(data)
    except struct.error:  # cut short
        return None
    return None


def _jpeg(data: bytes) -> Optional[Header]:
    """Its size is in the segment that starts its frame."""
    at = len(JPEG_SIGN)
    while at + 4 <= len(data):
        if data[at] != 0xFF:
            return None
        marker = data[at + 1]
        if marker == 0xFF:  # a fill byte
            at += 1
            continue
        if marker in FRAMES:
            height, width = struct.unpack(">HH", data[at + 5 : at + 9])
            return Header("image/jpeg", width, height)
        at += 2 + struct.unpack(">H", data[at + 2 : at + 4])[0]
    return None


def _webp(data: bytes) -> Optional[Header]:
    """By its first chunk: extended (VP8X), lossy (VP8) or lossless (VP8L)."""
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
    elif chunk == b"VP8 ":
        width, height = (side & 0x3FFF for side in struct.unpack("<HH", data[26:30]))
    elif chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    else:
        return None
    return Header("image/webp", width, height)


class GenerateImage:
    """generate_image: an image the image model of the chat's server makes,
    shown to the person (a conversation.Tool). The server's refusal, or an
    answer that is no image, goes to the model as a refusal it can explain."""

    name = GENERATE

    def __init__(self, client: Client):
        self.client = client

    def offered(self) -> Dict[str, Any]:
        return tool(GENERATE, DESCRIPTION, SCHEMA)

    def call(self, given: Dict[str, Any], running: Running) -> Tuple[str, bool]:
        prompt, size = given.get("prompt"), given.get("size")
        if not isinstance(prompt, str) or not prompt.strip():
            return NOT_MADE.format(why=NO_PROMPT), True
        if size is not None and not (isinstance(size, str) and SIZE.fullmatch(size)):
            return NOT_MADE.format(why=WRONG_SIZE), True
        try:
            data = self.client.generate(prompt, size)
        except ProviderError as e:
            return NOT_MADE.format(why=e), True
        found = header(data)
        if found is None:
            return NOT_MADE.format(why=NOT_AN_IMAGE), True
        name = " ".join(prompt.split())
        if len(name) > NAME_LETTERS:
            name = name[: NAME_LETTERS - 1] + "…"
        running.show(Image(data, found.mime, name))
        return SHOWN.format(width=found.width, height=found.height), False
