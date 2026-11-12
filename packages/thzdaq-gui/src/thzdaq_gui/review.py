"""A change of a text looked at hunk by hunk, as VS Code shows an edit: each
hunk (lines of the text it replaces, the lines it puts there) is taken (✓) or
not (✗), one by one or all at once. Hunks come from difflib, by lines.

Where the change comes from says what a hunk not decided yet counts as:
- OUTSIDE: its file changed on disk (an agent, another editor) while nothing
  here was unsaved; the change is made already, ✗ takes it back;
- PROPOSED: the assistant proposes it (code asked for, a fix); nothing of it
  is taken until ✓;
- COMPARED: its file changed on disk while the text here had changes not
  saved; ✓ takes the file's hunk, ✗ keeps the text here.

The text with what was decided is text(); rows() is the text as it is shown
while some hunk waits: each such hunk's lines that go, then those that come.
No Qt: the editor shows a Review and calls its methods."""

import difflib
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, List, Optional, Sequence, Tuple


class Source(str, Enum):
    OUTSIDE = "outside"
    PROPOSED = "proposed"
    COMPARED = "compared"


class Decision(str, Enum):
    WAITING = "waiting"
    TAKEN = "taken"
    LEFT = "left"


class Kind(str, Enum):
    """Of a row shown."""

    SAME = "same"  # a line of the text, whatever is decided
    GOES = "goes"  # a line a waiting hunk takes away
    COMES = "comes"  # a line a waiting hunk puts in


@dataclass(frozen=True)
class Hunk:
    start: int  # the first line of the base it replaces (from 0)
    old: Tuple[str, ...]  # the lines of the base it replaces (with their ends)
    new: Tuple[str, ...]  # the lines it puts there


@dataclass(frozen=True)
class Row:
    text: str  # without its line's end
    kind: Kind
    hunk: Optional[int] = None  # the waiting hunk it belongs to
    line: Optional[int] = None  # its line in text() (from 1); None: not in it


def hunks(base: str, proposed: str) -> Tuple[Hunk, ...]:
    """What differs between the two texts, by lines."""
    old = base.splitlines(keepends=True)
    new = proposed.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return tuple(
        Hunk(i1, tuple(old[i1:i2]), tuple(new[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )


@dataclass
class Review:
    base: str  # the text before the change
    proposed: str  # the text with all of it
    source: Source
    hunks: Tuple[Hunk, ...] = field(init=False)
    decisions: List[Decision] = field(init=False)

    def __post_init__(self):
        self.hunks = hunks(self.base, self.proposed)
        self.decisions = [Decision.WAITING] * len(self.hunks)

    # Deciding
    def take(self, index: int) -> None:
        self.decisions[index] = Decision.TAKEN

    def leave(self, index: int) -> None:
        self.decisions[index] = Decision.LEFT

    def take_all(self) -> None:
        for index in self.waiting():
            self.take(index)

    def leave_all(self) -> None:
        for index in self.waiting():
            self.leave(index)

    def waiting(self) -> List[int]:
        return [i for i, d in enumerate(self.decisions) if d is Decision.WAITING]

    def done(self) -> bool:
        return not self.waiting()

    def taken(self, index: int) -> bool:
        """Whether the hunk is in text(): taken, or waiting in a change made
        already."""
        decision = self.decisions[index]
        if decision is Decision.WAITING:
            return self.source is Source.OUTSIDE
        return decision is Decision.TAKEN

    # The text
    def text(self) -> str:
        """The base with the hunks taken."""
        return "".join(line for line, _, _ in self._lines(shown=False))

    def rows(self) -> List[Row]:
        """The text as shown: a waiting hunk's lines that go and those that
        come in place of its lines, the rest as text() has it."""
        rows: List[Row] = []
        number = 0
        for line, kind, hunk in self._lines(shown=True):
            counted = kind is Kind.SAME or (kind is Kind.COMES) == self.taken(hunk)
            number += counted
            shown = number if counted else None
            rows.append(Row(line.rstrip("\r\n"), kind, hunk, shown))
        return rows

    def first_row(self, index: int) -> Optional[int]:
        """The row a waiting hunk's lines start at in rows()."""
        return next((i for i, row in enumerate(self.rows()) if row.hunk == index), None)

    def _lines(self, shown: bool) -> Iterator[Tuple[str, Kind, Optional[int]]]:
        """Each line with its kind and its waiting hunk: shown, a waiting
        hunk's lines that go and come; else the lines of text()."""
        old = self.base.splitlines(keepends=True)
        at = 0
        for index, hunk in enumerate(self.hunks):
            for line in old[at : hunk.start]:
                yield line, Kind.SAME, None
            at = hunk.start + len(hunk.old)
            if shown and self.decisions[index] is Decision.WAITING:
                for line in hunk.old:
                    yield line, Kind.GOES, index
                for line in hunk.new:
                    yield line, Kind.COMES, index
            else:
                for line in hunk.new if self.taken(index) else hunk.old:
                    yield line, Kind.SAME, None
        for line in old[at:]:
            yield line, Kind.SAME, None


def joined(rows: Sequence[Row]) -> str:
    """Rows as the editor's lines."""
    return "\n".join(row.text for row in rows)
