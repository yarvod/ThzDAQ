"""A conversation with the model and its tools: the bench's
(thzdaq_api.tools, Bench) and the assistant's own (images.py: an image made
and shown to the person), each a Tool.

A turn answers one message of the person:
1. the model is asked with the messages so far and the tools;
2. it answers with text, or with tool calls;
3. each call runs: a bench's goes to the bench as the assistant (rights,
   limits, a person's consent in the window), an own one does what it does
   and may show the person an image (Running); what it answers, a refusal
   too, goes back to the model as the tool's message;
4. again, until the model answers with text alone, or MAX_STEPS steps.

What the person writes while a turn runs waits (queue) and joins the
conversation at the next step, as the model is asked again: the turn goes on
with it, and a turn whose model answered goes on while something waits.

A turn runs apart from the window (a call waits for a person, a measurement,
the model). stop() ends it at once: from then on the turn adds nothing and
tells nothing (what a call made meanwhile, an image, is dropped), and a call
it made that has no answer yet is answered "stopped". What the call asked of
the bench goes on: a run it started runs, a dialog it opened still waits for
the person.

What a turn does is told as the chat's events (chat.Listener); how it ended
is what say() returns. builtin.py runs it as a chat of the dock.
"""

import json
import threading
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from thzdaq_api import present
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.tools import Reach
from thzdaq_api.tools import Tool as Operation

from thzdaq_gui.assistant.attachments import Content
from thzdaq_gui.assistant.chat import Call, Image, Listener, Outcome, Used
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


class Stopped(Exception):
    """The turn was stopped: it adds and tells nothing more."""


class Running:
    """A call as it runs: the bench as the assistant reached it, and what the
    call tells the turn's listener; Stopped once the turn was stopped (what
    the call made is dropped)."""

    def __init__(
        self,
        conversation: "Conversation",
        turn: object,
        call: str,
        reach: Reach,
        listener: Listener,
    ):
        self.reach = reach
        self._conversation, self._turn = conversation, turn
        self._call, self._listener = call, listener

    def progress(
        self, done: float, total: Optional[float], message: Optional[str] = None
    ) -> None:
        """How far it is (a measurement waited for)."""
        self._conversation._tell(
            self._turn, self._listener.progress, self._call, done, total
        )

    def show(self, image: Image) -> None:
        """An image shown to the person."""
        self._conversation._tell(self._turn, self._listener.image, image)


class Tool(Protocol):
    """A tool the model is offered, as the conversation calls it."""

    name: str

    def offered(self) -> Dict[str, Any]:
        """As chat/completions takes it (provider.tool)."""

    def call(self, given: Dict[str, Any], running: Running) -> Tuple[str, bool]:
        """What it answers the model for the arguments given, and whether it
        refused or failed (the model reads why and goes on)."""


class Bench:
    """A tool of the bench (thzdaq_api.tools): an operation called on the
    bench as the assistant reached it; what the bench refuses, a wrong
    argument too, goes to the model as a refusal."""

    def __init__(self, operation: Operation):
        self.operation = operation
        self.name = operation.name

    def offered(self) -> Dict[str, Any]:
        found = self.operation
        return tool(found.name, found.description(), found.schema())

    def call(self, given: Dict[str, Any], running: Running) -> Tuple[str, bool]:
        try:
            args = self.operation.arguments(given)
            return self.operation.call(running.reach, args, running.progress), False
        except LabError as e:
            return present.failure(e), True


class Conversation:
    def __init__(self, max_steps: int = MAX_STEPS):
        self.max_steps = max_steps
        self.messages: List[Message] = []  # after the system prompt
        self.system: Optional[str] = None  # None: made at the next turn
        self._forgotten = 0  # forget_bench counts: a prompt made before is not kept
        # What a turn tells is told under it, so nothing is told once stopped;
        # a listener may stop the turn as it hears it
        self._lock = threading.RLock()
        self._turn: Optional[object] = None  # the turn running
        self._waiting: List[Content] = []  # the person's, for the next step

    def restore(self, messages: Sequence[Message]) -> None:
        """The messages of a conversation kept before, to go on with it: the
        next turn adds to them, with a system prompt made anew."""
        with self._lock:
            self.messages = list(messages)

    def count(self) -> int:
        """Messages so far: a turn's begin with since()."""
        with self._lock:
            return len(self.messages)

    def since(self, count: int) -> List[Message]:
        """The messages added after the first count."""
        with self._lock:
            return self.messages[count:]

    def forget_bench(self) -> None:
        """The bench or the person's instructions changed: the next turn
        makes the system prompt anew; a turn running keeps its own."""
        with self._lock:
            self.system = None
            self._forgotten += 1

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
        tools: Sequence[Operation],
        reach: Reach,
        prompt: Callable[[Reach], str],
        listener: Listener,
        own: Sequence[Tool] = (),
    ) -> Tuple[Outcome, str]:
        """Answer the person's message (None: only those that wait): how the
        turn ended and, when it failed, why. The model is offered the bench's
        tools and the assistant's own ones. prompt(reach) makes the system
        prompt when the bench is new to the conversation."""
        offered = [*(Bench(operation) for operation in tools), *own]
        try:
            return self._say(turn, content, client, offered, reach, prompt, listener)
        except Stopped:
            return Outcome.STOPPED, ""
        finally:
            with self._lock:
                if self._turn is turn:
                    self._turn = None

    def _say(self, turn, content, client, tools, reach, prompt, listener):
        if content is not None:
            self._add(turn, {"role": "user", "content": content})
        with self._lock:  # the turn keeps the prompt it begins with
            system, forgotten = self.system, self._forgotten
        try:
            if system is None:
                system = prompt(reach)
                self._set_system(turn, system, forgotten)
        except LabError as e:
            return Outcome.FAILED, f"the bench cannot be asked: {e}"
        found = {each.name: each for each in tools}
        offered = [each.offered() for each in tools]

        def heard(piece: str) -> None:
            self._tell(turn, listener.text, piece)

        def thought(piece: str) -> None:
            self._tell(turn, listener.thought, piece)

        for _ in range(self.max_steps):
            self._take(turn, listener)
            self._tell(turn, listener.asking)
            try:
                reply = client.complete(
                    self._asked(turn, system), offered, heard, thought=thought
                )
            except ProviderError as e:
                return Outcome.FAILED, str(e)
            self._add(turn, reply.message())
            if reply.usage is not None:
                self._tell(turn, listener.usage, used(reply.usage))
            if not reply.calls:
                if self.waiting():
                    continue  # the person wrote meanwhile: it answers that too
                return Outcome.ANSWERED, ""
            for call in reply.calls:
                self._tell(turn, listener.called, shown(call))
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
        """What the tool answered the call, and whether it was refused or
        wrong: the model reads either and goes on."""
        chosen = found.get(call.name)
        try:
            if chosen is None:
                raise LabError(
                    ErrorCode.UNKNOWN_OPERATION,
                    f"No tool {call.name!r}",
                    f"known: {', '.join(found)}",
                )
            given = arguments(call)
        except LabError as e:
            return present.failure(e), True
        return chosen.call(given, Running(self, turn, call.id, reach, listener))

    def _take(self, turn: object, listener: Listener) -> None:
        """What waited joins the conversation."""
        with self._lock:
            self._check(turn)
            taken, self._waiting = self._waiting, []
            self.messages += [{"role": "user", "content": c} for c in taken]
            if taken:
                listener.taken(len(taken))

    def _asked(self, turn: object, system: str) -> List[Message]:
        with self._lock:
            self._check(turn)
            return [{"role": "system", "content": system}] + list(self.messages)

    def _set_system(self, turn: object, prompt: str, forgotten: int) -> None:
        """Kept for the next turns unless forgotten while it was made."""
        with self._lock:
            self._check(turn)
            if forgotten == self._forgotten:
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


def shown(call: ToolCall) -> Call:
    """A call as the chat shows it: arguments that do not read show none (the
    model reads why in the call's answer)."""
    try:
        given = arguments(call)
    except LabError:
        given = {}
    return Call(call.id, call.name, given)


def used(usage: Usage) -> Used:
    """A step's tokens; the conversation fills what the model read and wrote
    in it (the last step's is the context now; summed over steps, what was
    read is what the server billed, not the context)."""
    return Used(
        usage.prompt, usage.completion, usage.reasoning,
        usage.prompt + usage.completion, usage.cached,
    )  # fmt: skip


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
