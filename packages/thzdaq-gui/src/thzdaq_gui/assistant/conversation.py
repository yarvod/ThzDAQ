"""A conversation with the model and the bench's tools (thzdaq_api.tools).

A turn answers one message of the person:
1. the model is asked with the messages so far and the tools;
2. it answers with text, or with tool calls;
3. each call goes to the bench as the assistant (rights, limits, a person's
   consent in the window), and what it answers, a refusal too, goes back to
   the model as the tool's message;
4. again, until the model answers with text alone, or MAX_STEPS steps.

What the person writes while a turn runs waits (queue) and joins the
conversation at the next step, as the model is asked again: the turn goes on
with it, and a turn whose model answered goes on while something waits.

A turn runs apart from the window (a call waits for a person, a measurement,
the model). stop() ends it at once: from then on the turn adds nothing and
tells nothing, and a call it made that has no answer yet is answered
"stopped". What the call asked of the bench goes on: a run it started runs,
a dialog it opened still waits for the person.
"""

import json
import threading
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from thzdaq_api import present
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.tools import Reach, Tool, by_name

from thzdaq_gui.assistant.attachments import Content
from thzdaq_gui.assistant.provider import (
    Client,
    Message,
    ProviderError,
    ToolCall,
    Usage,
    tool,
)

MAX_STEPS = 20  # questions to the model in one turn
STOPPED = "stopped by the person before it answered"


class Outcome(str, Enum):
    ANSWERED = "answered"  # the model answered in words
    STOPPED = "stopped"  # the person stopped it
    STEPS = "steps"  # it took MAX_STEPS steps without an answer
    FAILED = "failed"  # the model's server or the daemon failed


class Listener(Protocol):
    """What a turn tells as it goes, in its own thread."""

    def asking(self) -> None:
        """The model is asked: a step begins."""

    def taken(self, count: int) -> None:
        """The first count messages that waited joined the conversation."""

    def thought(self, piece: str) -> None:
        """A piece of what the model thinks before it answers."""

    def usage(self, usage: Usage) -> None:
        """The tokens a step took."""

    def text(self, piece: str) -> None:
        """A piece of the model's answer."""

    def called(self, call: ToolCall) -> None:
        """A tool call starts."""

    def progress(self, call: str, done: float, total: Optional[float]) -> None:
        """How far a call is (a measurement waited for)."""

    def answered(self, call: str, text: str, failed: bool) -> None:
        """What a call answered; failed: refused or wrong."""


class Stopped(Exception):
    """The turn was stopped: it adds and tells nothing more."""


class Conversation:
    def __init__(self, max_steps: int = MAX_STEPS):
        self.max_steps = max_steps
        self.messages: List[Message] = []  # after the system prompt
        self.system: Optional[str] = None  # None: made at the next turn
        # What a turn tells is told under it, so nothing is told once stopped;
        # a listener may stop the turn as it hears it
        self._lock = threading.RLock()
        self._turn: Optional[object] = None  # the turn running
        self._waiting: List[Content] = []  # the person's, for the next step

    def forget_bench(self) -> None:
        """The bench changed: the next turn tells the model it anew."""
        with self._lock:
            self.system = None

    def begin(self) -> object:
        """A turn starts; what it adds and tells carries this token."""
        with self._lock:
            if self._turn is not None:
                raise RuntimeError("a turn runs already")
            self._turn = object()
            return self._turn

    def queue(self, content: Content) -> None:
        """A message of the person while a turn runs: it joins at the next
        step."""
        with self._lock:
            self._waiting.append(content)

    def waiting(self) -> int:
        """Messages that wait for the next step."""
        with self._lock:
            return len(self._waiting)

    def stop(self) -> int:
        """End the turn running at once; a call without an answer is answered
        STOPPED, so the next turn asks the model with whole messages. What
        waited is dropped: how many."""
        with self._lock:
            self._turn = None
            dropped, self._waiting = len(self._waiting), []
            last = next(
                (m for m in reversed(self.messages) if m["role"] == "assistant"), {}
            )
            answered = {m["tool_call_id"] for m in self.messages if m["role"] == "tool"}
            for call in last.get("tool_calls") or ():
                if call["id"] not in answered:
                    self.messages.append(answer(call["id"], STOPPED))
            return dropped

    def say(
        self,
        turn: object,
        content: Optional[Content],
        client: Client,
        tools: Sequence[Tool],
        reach: Reach,
        prompt: Callable[[Reach], str],
        listener: Listener,
    ) -> Tuple[Outcome, str]:
        """Answer the person's message (None: only those that wait): how the
        turn ended and, when it failed, why. prompt(reach) makes the system
        prompt when the bench is new to the conversation."""
        try:
            return self._say(turn, content, client, tools, reach, prompt, listener)
        except Stopped:
            return Outcome.STOPPED, ""
        finally:
            with self._lock:
                if self._turn is turn:
                    self._turn = None

    def _say(self, turn, content, client, tools, reach, prompt, listener):
        if content is not None:
            self._add(turn, {"role": "user", "content": content})
        try:
            if self.system is None:
                self._set_system(turn, prompt(reach))
        except LabError as e:
            return Outcome.FAILED, f"the bench cannot be asked: {e}"
        found = by_name(tuple(tools))
        offered = [tool(t.name, t.description(), t.schema()) for t in tools]

        def heard(piece: str) -> None:
            self._tell(turn, listener.text, piece)

        def thought(piece: str) -> None:
            self._tell(turn, listener.thought, piece)

        for _ in range(self.max_steps):
            self._take(turn, listener)
            self._tell(turn, listener.asking)
            try:
                reply = client.complete(
                    self._asked(turn), offered, heard, thought=thought
                )
            except ProviderError as e:
                return Outcome.FAILED, str(e)
            self._add(turn, reply.message())
            if reply.usage is not None:
                self._tell(turn, listener.usage, reply.usage)
            if not reply.calls:
                if self.waiting():
                    continue  # the person wrote meanwhile: it answers that too
                return Outcome.ANSWERED, ""
            for call in reply.calls:
                self._tell(turn, listener.called, call)
                told, failed = self._call(turn, call, found, reach, listener)
                self._add(turn, answer(call.id, told))
                self._tell(turn, listener.answered, call.id, told, failed)
        return Outcome.STEPS, ""

    def _call(
        self,
        turn: object,
        call: ToolCall,
        found: Dict[str, Tool],
        reach: Reach,
        listener: Listener,
    ) -> Tuple[str, bool]:
        """What the bench answered the call, and whether it was refused or
        wrong: the model reads either and goes on."""

        def progress(done: float, total: Optional[float], message: Optional[str]):
            self._tell(turn, listener.progress, call.id, done, total)

        try:
            chosen = found.get(call.name)
            if chosen is None:
                raise LabError(
                    ErrorCode.UNKNOWN_OPERATION,
                    f"No tool {call.name!r}",
                    f"known: {', '.join(found)}",
                )
            args = chosen.arguments(arguments(call))
            return chosen.call(reach, args, progress), False
        except LabError as e:
            return present.failure(e), True

    def _take(self, turn: object, listener: Listener) -> None:
        """What waited joins the conversation."""
        with self._lock:
            self._check(turn)
            taken, self._waiting = self._waiting, []
            self.messages += [{"role": "user", "content": c} for c in taken]
            if taken:
                listener.taken(len(taken))

    def _asked(self, turn: object) -> List[Message]:
        with self._lock:
            self._check(turn)
            return [{"role": "system", "content": self.system}] + list(self.messages)

    def _set_system(self, turn: object, prompt: str) -> None:
        with self._lock:
            self._check(turn)
            self.system = prompt

    def _add(self, turn: object, message: Message) -> None:
        with self._lock:
            self._check(turn)
            self.messages.append(message)

    def _tell(self, turn: object, tell: Callable[..., None], *told: Any) -> None:
        with self._lock:
            self._check(turn)
            tell(*told)

    def _check(self, turn: object) -> None:
        if self._turn is not turn:
            raise Stopped()


def answer(call: str, text: str) -> Message:
    return {"role": "tool", "tool_call_id": call, "content": text}


def arguments(call: ToolCall) -> Dict[str, Any]:
    """The arguments the model wrote; LabError when they are not a JSON object."""
    try:
        given = json.loads(call.arguments or "{}")
    except ValueError as e:
        raise LabError(
            ErrorCode.INVALID_ARGUMENTS,
            f"{call.name}: the arguments are not JSON ({e})",
            "give them as a JSON object",
        ) from None
    if not isinstance(given, dict):
        raise LabError(
            ErrorCode.INVALID_ARGUMENTS,
            f"{call.name}: the arguments are not a JSON object",
            "give them as a JSON object",
        )
    return given
