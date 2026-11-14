"""What a person attaches to a message: an image the model sees (a model that
sees images; the server of one that does not refuses it), a text file whose
text goes into the message, any other file by its path (a script the
assistant writes may read it)."""

import base64
import mimetypes
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

TEXT_BYTES = 256 * 1024  # a longer text file goes by its path
IMAGE_BYTES = 20 * 1024 * 1024  # what servers take at most, about
PASTED = "pasted.png"

Content = Union[str, List[Dict[str, Any]]]  # a message's, as servers take it


class Kind(str, Enum):
    IMAGE = "image"
    TEXT = "text"
    FILE = "file"  # by its path


class AttachmentError(Exception):
    """It cannot be attached: why."""


@dataclass(frozen=True)
class Attachment:
    name: str
    kind: Kind
    path: Optional[str] = None  # None: pasted
    data: bytes = b""  # an image's
    mime: str = ""  # an image's
    text: str = ""  # a text file's

    @staticmethod
    def of_file(path: Union[str, Path]) -> "Attachment":
        """A file as it goes: an image, its text, or its path."""
        path = Path(path)
        try:
            size = path.stat().st_size
            mime = mimetypes.guess_type(path.name)[0] or ""
            if mime.startswith("image/"):
                if size > IMAGE_BYTES:
                    raise AttachmentError(f"{path.name}: an image over 20 MB")
                return Attachment.image(path.read_bytes(), path.name, mime, path)
            if size <= TEXT_BYTES:
                text = text_of(path.read_bytes())
                if text is not None:
                    return Attachment(path.name, Kind.TEXT, str(path), text=text)
        except OSError as e:
            raise AttachmentError(f"{path.name}: {e.strerror or e}") from None
        if not path.is_file():
            raise AttachmentError(f"{path.name}: not a file")
        return Attachment(path.name, Kind.FILE, str(path))

    @staticmethod
    def image(
        data: bytes,
        name: str = PASTED,
        mime: str = "image/png",
        path: Optional[Path] = None,
    ) -> "Attachment":
        return Attachment(
            name, Kind.IMAGE, str(path) if path else None, data=data, mime=mime
        )

    def told(self) -> str:
        """What the message says of it in words."""
        where = f" ({self.path})" if self.path else ""
        if self.kind is Kind.TEXT:
            return f"Attached file {self.name}{where}:\n```\n{self.text}\n```"
        if self.kind is Kind.FILE:
            return f"Attached file {self.name}{where}: read it from there"
        return f"Attached image {self.name}{where}"

    def part(self) -> Dict[str, Any]:
        """An image as a part of the message."""
        encoded = base64.b64encode(self.data).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{self.mime};base64,{encoded}"},
        }


def text_of(data: bytes) -> Optional[str]:
    """The text of a file; None for one that is not text."""
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def content(text: str, attachments: Sequence[Attachment]) -> Content:
    """A person's message with what is attached: words alone without images,
    parts (the words, then each image) with them."""
    words = "\n\n".join([text, *(a.told() for a in attachments)]).strip()
    images = [a.part() for a in attachments if a.kind is Kind.IMAGE]
    if not images:
        return words
    return [{"type": "text", "text": words}, *images]
