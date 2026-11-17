"""The built-in assistant's conversations, kept as files of the program apart
from any workspace (never in its git): under the program's data
(settings.chats_dir()), a folder per workspace, named by the workspace's
folder and a hash of its path, and in it a folder per conversation:

    <workspace>/<id>/chat.jsonl   a line of its version, then a line per turn
    <workspace>/<id>/meta.json    its title, when it began, when a turn ended last
    <workspace>/<id>/<hash>.png   each image attached, once, by the hash of its bytes

A turn's line keeps what the person said, what the turn told (pieces joined,
no progress, how long each thought took), how it ended and how long it took,
and the messages it added for the model: enough to tell it again the way it
was told (chat.Replay), so the view model shows it as it was shown, and to go
on with it. An image is a file in both, never a copy within the line.

A turn is kept once it ended or was stopped (Recorder), never piece by piece.
One thread of the shelf reads and writes, in the order asked: a conversation
listed or opened right after a turn of it ended, or it was renamed, is read
as it is kept now. The thread ends once nothing waits, and the program's exit
waits for it. No Qt.
"""

import hashlib
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence

from thzdaq_gui.assistant.attachments import Attachment, Kind
from thzdaq_gui.assistant.chat import Call, Kept, Listener, Outcome, Replay, Said, Used
from thzdaq_gui.assistant.provider import Message

logger = logging.getLogger(__name__)

VERSION = 1  # of a conversation's file
CHAT, META = "chat.jsonl", "meta.json"
TITLE_LETTERS = 80
UNTITLED = "Chat"
NEWER = "It was kept by a newer version of the program"
UNREAD = "{count} of its turns could not be read"
FILE_UNREAD = "The chat could not be read: {why}"

Restore = Callable[[List[Message]], None]


def workspace_key(workspace: Path) -> str:
    """The folder of a workspace's conversations: its name, readable, and a
    hash of its path, apart from any other of that name."""
    name = re.sub(r"[^\w.-]+", "-", workspace.name).strip("-.")[:40] or "root"
    path = os.path.normcase(str(workspace))
    return f"{name}-{hashlib.sha1(path.encode('utf-8')).hexdigest()[:10]}"


def title_of(said: Optional[Said]) -> str:
    """A conversation's title: the first line of what the person said first,
    else what was attached."""
    if said is None:
        return UNTITLED
    line = next((line.strip() for line in said.text.splitlines() if line.strip()), "")
    line = line or ", ".join(given.name for given in said.attachments)
    if len(line) > TITLE_LETTERS:
        line = line[: TITLE_LETTERS - 1] + "…"
    return line or UNTITLED


def _meta(chat: Kept) -> Dict[str, Any]:
    """What meta.json keeps of a conversation as it begins."""
    return {
        "id": chat.id,
        "title": chat.title,
        "created": chat.updated,
        "updated": chat.updated,
        "workspace": str(chat.workspace),
    }


@dataclass
class Turn:
    """A turn over, as it is kept: told is what it told, each a list (its
    kind, then what it told), what the person said meanwhile as Said."""

    said: Optional[Said]
    told: List[list]
    outcome: Outcome
    why: str
    seconds: float
    messages: List[Message]


class Recorder:
    """A turn of a kept conversation, the listener its chat tells: what is
    told goes on to the turn's own listener and is kept, pieces joined; once
    the turn ended (or was stopped: finish), the shelf keeps it, and nothing
    told after is kept. Told from the turn's thread; said() and finish() from
    the chat's owner."""

    def __init__(
        self,
        shelf: "Shelf",
        chat: Kept,
        said: Optional[Said],
        waited: Sequence[Said],
        listener: Listener,
        messages: Callable[[], List[Message]],
    ):
        self.shelf, self.chat, self.listener = shelf, chat, listener
        self._said = said
        self._messages = messages  # what the turn added for the model
        self._lock = threading.Lock()
        self._began = time.monotonic()
        # What was told; None once kept. Said while no turn kept it comes first
        self._told: Optional[List[list]] = [["said", s] for s in waited]
        self._thought: Optional[list] = None  # the thought going on: its entry
        self._thought_began = 0.0

    def said(self, said: Said) -> bool:
        """What the person said while the turn runs; False once the turn was
        kept (what is said then goes with the next one)."""
        with self._lock:
            if self._told is None:
                return False
            self._told.append(["said", said])
            return True

    def finish(self, outcome: Outcome, why: str) -> None:
        """The turn is over: kept as it is now (the first time only)."""
        with self._lock:
            if self._told is None:
                return
            self._thought_over()
            told, self._told = self._told, None
        seconds = time.monotonic() - self._began
        for entry in told:
            if entry[0] in ("thought", "text"):
                entry[1] = "".join(entry[1])
        self.shelf.keep(
            self.chat,
            Turn(self._said, told, outcome, why, seconds, self._messages()),
        )

    # chat.Listener
    def asking(self) -> None:
        self._keep(["asking"])
        self.listener.asking()

    def taken(self, count: int) -> None:
        self._keep(["taken", count])
        self.listener.taken(count)

    def thought(self, piece: str) -> None:
        with self._lock:
            if self._told is not None:
                if self._thought is None:
                    self._thought = ["thought", [], None]
                    self._thought_began = time.monotonic()
                    self._told.append(self._thought)
                self._thought[1].append(piece)
        self.listener.thought(piece)

    def text(self, piece: str) -> None:
        with self._lock:
            if self._told is not None:
                self._thought_over()
                last = self._told[-1] if self._told else None
                if last is not None and last[0] == "text":
                    last[1].append(piece)
                else:
                    self._told.append(["text", [piece]])
        self.listener.text(piece)

    def called(self, call: Call) -> None:
        self._keep(["called", call.id, call.name, dict(call.arguments)], over=True)
        self.listener.called(call)

    def progress(self, call: str, done: float, total: Optional[float]) -> None:
        self.listener.progress(call, done, total)

    def answered(self, call: str, text: str, failed: bool) -> None:
        self._keep(["answered", call, text, failed])
        self.listener.answered(call, text, failed)

    def usage(self, used: Used) -> None:
        self._keep(["usage", used.read, used.written, used.reasoning, used.context])
        self.listener.usage(used)

    def ended(self, outcome: Outcome, why: str) -> None:
        self.finish(outcome, why)
        self.listener.ended(outcome, why)

    def _keep(self, entry: list, over: bool = False) -> None:
        """over: it ends the thought going on."""
        with self._lock:
            if self._told is not None:
                if over:
                    self._thought_over()
                self._told.append(entry)

    def _thought_over(self) -> None:
        if self._thought is not None:
            self._thought[2] = time.monotonic() - self._thought_began
            self._thought = None


class _Images:
    """The images of a conversation's folder, a file each, by the hash of its
    bytes."""

    def __init__(self, folder: Path):
        self.folder = folder

    def keep(self, data: bytes, mime: str) -> str:
        name = hashlib.sha1(data).hexdigest()[:16]
        name += mimetypes.guess_extension(mime) or ""
        path = self.folder / name
        if not path.exists():
            path.write_bytes(data)
        return name

    def read(self, name: str) -> bytes:
        """OSError when it is gone."""
        return (self.folder / Path(name).name).read_bytes()


def _said(said: Said, images: _Images) -> Dict[str, Any]:
    return {
        "text": said.text,
        "attachments": [_attachment(given, images) for given in said.attachments],
    }


def _attachment(given: Attachment, images: _Images) -> Dict[str, Any]:
    kept: Dict[str, Any] = {"name": given.name, "kind": given.kind.value}
    kept["path"] = given.path
    if given.kind is Kind.IMAGE:
        kept.update(file=images.keep(given.data, given.mime), mime=given.mime)
    elif given.kind is Kind.TEXT:
        kept["text"] = given.text
    return kept


def _said_of(kept: Dict[str, Any], images: _Images) -> Said:
    return Said(
        kept["text"],
        tuple(_attachment_of(given, images) for given in kept["attachments"]),
    )


def _attachment_of(kept: Dict[str, Any], images: _Images) -> Attachment:
    kind = Kind(kept["kind"])
    if kind is Kind.IMAGE:
        data = images.read(kept["file"])
        return Attachment(
            kept["name"], kind, kept["path"], data=data, mime=kept["mime"]
        )
    return Attachment(kept["name"], kind, kept["path"], text=kept.get("text", ""))


def _message(message: Message, images: _Images) -> Message:
    """A message for the model, its images as files."""
    content = message.get("content")
    if not isinstance(content, list):
        return message
    return {**message, "content": [_part(part, images) for part in content]}


def _part(part: Dict[str, Any], images: _Images) -> Dict[str, Any]:
    image = Attachment.of_part(part)
    if image is None:
        return part
    return {"image": images.keep(image.data, image.mime), "mime": image.mime}


def _message_of(kept: Message, images: _Images) -> Message:
    content = kept.get("content")
    if not isinstance(content, list):
        return kept
    return {**kept, "content": [_part_of(part, images) for part in content]}


def _part_of(kept: Dict[str, Any], images: _Images) -> Dict[str, Any]:
    if "image" not in kept:
        return kept
    return Attachment.image(images.read(kept["image"]), mime=kept["mime"]).part()


def _entry(entry: list, images: _Images) -> list:
    """What a turn told, as its line keeps it."""
    if entry[0] == "said":
        return ["said", _said(entry[1], images)]
    return entry


# What a turn told, by its kind (the Replay method that tells it again): what
# it told as its line keeps it -> the method's arguments
_TOLD: Dict[str, Callable[..., tuple]] = {
    "asking": lambda images: (),
    "taken": lambda images, count: (count,),
    "thought": lambda images, text, seconds: (text, seconds),
    "text": lambda images, text: (text,),
    "called": lambda images, call, name, arguments: (Call(call, name, arguments),),
    "answered": lambda images, call, text, failed: (call, text, failed),
    "usage": lambda images, *used: (Used(*used),),
    "said": lambda images, said: (_said_of(said, images),),
}


def _told(replay: Replay, images: _Images, kind: str, *kept: Any) -> Callable[[], None]:
    """What a turn told, read, to be told again (KeyError: a kind unknown)."""
    given = _TOLD[kind](images, *kept)
    return partial(getattr(replay, kind), *given)


@dataclass
class _Read:
    """A turn read, ready to be told again."""

    said: Optional[Said]
    told: List[Callable[[], None]]
    outcome: Outcome
    why: str
    seconds: Optional[float]
    messages: List[Message]


def _read(kept: Dict[str, Any], images: _Images, replay: Replay) -> _Read:
    """A turn's line; KeyError, TypeError, ValueError or OSError (an image
    gone) when it does not read."""
    said = kept["said"]
    return _Read(
        None if said is None else _said_of(said, images),
        [_told(replay, images, *told) for told in kept["told"]],
        Outcome(kept["ended"]),
        kept["why"],
        kept.get("seconds"),
        [_message_of(message, images) for message in kept["messages"]],
    )


class Shelf:
    """The conversations of the built-in chat as files under root, read and
    written by one thread of its own, in the order asked; nothing waits for
    it."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._jobs: Deque[Callable[[], None]] = deque()
        self._lock = threading.Lock()
        self._working = False  # a thread takes the jobs

    def folder(self, chat: Kept) -> Path:
        return self.root / workspace_key(chat.workspace) / chat.id

    def new(self, workspace: Path, said: Optional[Said]) -> Kept:
        """A conversation that begins with what the person said: kept from
        now on, its turns as they end."""
        now = time.time()
        chat = Kept(
            f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}",
            title_of(said),
            now,
            workspace,
        )
        self._do(lambda: self._begin(chat))
        return chat

    def keep(self, chat: Kept, turn: Turn) -> None:
        self._do(lambda: self._append(chat, turn))

    def rename(self, chat: Kept, title: str) -> None:
        self._do(lambda: self._retitle(chat, title))

    def chats(self, workspace: Path, found: Callable[[Sequence[Kept]], None]) -> None:
        """The workspace's conversations, the newest first, told to found."""
        self._do(lambda: found(self._chats(workspace)))

    def open(self, chat: Kept, restore: Restore, replay: Replay) -> None:
        """Read a conversation: its messages for the model go to restore,
        then it is told again to replay."""
        self._do(lambda: self._open(chat, restore, replay))

    # In the shelf's thread
    def _do(self, job: Callable[[], None]) -> None:
        with self._lock:
            self._jobs.append(job)
            if self._working:
                return
            self._working = True
        # Not a daemon: the program's exit waits for what is still to be kept
        threading.Thread(target=self._work, name="assistant chats").start()

    def _work(self) -> None:
        while True:
            with self._lock:
                if not self._jobs:
                    self._working = False
                    return
                job = self._jobs.popleft()
            job()

    def _begin(self, chat: Kept) -> None:
        folder = self.folder(chat)
        header = {"version": VERSION, "workspace": str(chat.workspace)}
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / CHAT, "a", encoding="utf-8") as file:
                file.write(json.dumps(header, ensure_ascii=False) + "\n")
            self._write_meta(folder, _meta(chat))
        except OSError as e:
            logger.warning(f"The chat {chat.id} is not kept: {e}")

    def _append(self, chat: Kept, turn: Turn) -> None:
        folder = self.folder(chat)
        images = _Images(folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            line = {
                "said": None if turn.said is None else _said(turn.said, images),
                "told": [_entry(entry, images) for entry in turn.told],
                "ended": turn.outcome.value,
                "why": turn.why,
                "seconds": round(turn.seconds, 3),
                "messages": [_message(message, images) for message in turn.messages],
            }
            with open(folder / CHAT, "a", encoding="utf-8") as file:
                file.write(json.dumps(line, ensure_ascii=False) + "\n")
            meta = self._meta(folder, chat)
            meta["updated"] = time.time()
            self._write_meta(folder, meta)
        except OSError as e:
            logger.warning(f"A turn of the chat {chat.id} is not kept: {e}")

    def _retitle(self, chat: Kept, title: str) -> None:
        folder = self.folder(chat)
        try:
            meta = self._meta(folder, chat)
            meta["title"] = title
            self._write_meta(folder, meta)
        except OSError as e:
            logger.warning(f"The chat {chat.id} is not renamed: {e}")

    def _chats(self, workspace: Path) -> List[Kept]:
        found = []
        for path in (self.root / workspace_key(workspace)).glob(f"*/{META}"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                found.append(
                    Kept(meta["id"], meta["title"], meta["updated"], workspace)
                )
            except (OSError, ValueError, KeyError) as e:
                logger.warning(f"{path} does not read: {e}")
        return sorted(found, key=lambda chat: chat.updated, reverse=True)

    def _open(self, chat: Kept, restore: Restore, replay: Replay) -> None:
        folder = self.folder(chat)
        images = _Images(folder)
        try:
            lines = (folder / CHAT).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []  # its first turn is not over yet
        except OSError as e:
            replay.opened(FILE_UNREAD.format(why=e))
            return
        turns: List[_Read] = []
        unread = 0
        for line in lines:
            try:
                kept = json.loads(line)
                if "version" in kept:
                    if kept["version"] > VERSION:
                        replay.opened(NEWER)
                        return
                    continue
                turns.append(_read(kept, images, replay))
            except (KeyError, TypeError, ValueError, OSError):
                unread += 1
        restore([message for turn in turns for message in turn.messages])
        for turn in turns:
            replay.began(turn.said)
            for tell in turn.told:
                tell()
            replay.ended(turn.outcome, turn.why, turn.seconds)
        replay.opened(UNREAD.format(count=unread) if unread else "")

    @staticmethod
    def _meta(folder: Path, chat: Kept) -> Dict[str, Any]:
        """As kept; as the chat knows it when that is gone."""
        try:
            return json.loads((folder / META).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return _meta(chat)

    @staticmethod
    def _write_meta(folder: Path, meta: Dict[str, Any]) -> None:
        """Whole or not at all: a listing never reads half of it."""
        written = folder / f"{META}.new"
        written.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        os.replace(written, folder / META)
