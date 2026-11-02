"""What waits for a person, until the first person answers or it times out.

An agent's operation waits in its call (outside every lock) and is withdrawn
when nobody answers in time: the call fails, the agent may ask again. A
question stays: wait_answer goes on waiting for it.
"""

import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from thzdaq_api.approvals import ANSWER_S, Answer, Approval, UserAnswer
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ApprovalAnswered, ApprovalRequested

from thzdaq_core.application.clock import wall_time
from thzdaq_core.application.events import EventBus

NOBODY = "no person can answer now: open the ThzDAQ window or thzdaq approvals watch"
TIMEOUT = "timeout"  # Answer.by when nobody answered
KEPT = 100  # answers kept for wait_answer after their question closed


@dataclass(frozen=True)
class Ask:
    """What a person reads to allow an agent's call."""

    title: str
    text: str
    warning: str = ""
    confirm: str = ""  # typed to allow it: a dangerous step
    value: Optional[str] = None  # the value asked for, in its unit: may be changed
    # It may harm the bench (a danger, a jump, beyond the warn range, another's
    # sweep): a person allows it even where an agent may do it alone
    risky: bool = False


class _Waiting:
    def __init__(self, approval: Approval):
        self.approval = approval
        self.answered = threading.Event()
        self.answer: Optional[Answer] = None


class Approvals:
    def __init__(self, events: EventBus, people: Callable[[], bool]):
        """people: whether a person can answer now (a window listens)."""
        self.events = events
        self.people = people
        self._waiting: Dict[int, _Waiting] = {}
        self._answers: Dict[int, Answer] = {}  # closed, for wait_answer
        self._last = 0
        self._lock = threading.Lock()

    def ask(
        self, ask: Ask, operation: str, origin: str, timeout: float = ANSWER_S
    ) -> Answer:
        """Wait for a person to allow an operation; not allowed when nobody can
        answer or nobody did in time."""
        if not self.people():
            return Answer(False, NOBODY)
        waiting = self._open(
            lambda id: Approval(
                id, origin, ask.title, ask.text, ask.warning, ask.confirm,
                ask.value, (), operation, wall_time(),
            )  # fmt: skip
        )
        waited = min(timeout, ANSWER_S)
        if not waiting.answered.wait(waited):
            nobody = Answer(False, f"nobody answered in {waited:g} s", by=TIMEOUT)
            return self._close(waiting, nobody)
        return waiting.answer

    def question(
        self,
        question: str,
        options: Tuple[str, ...],
        origin: str,
        timeout: float = ANSWER_S,
    ) -> UserAnswer:
        """An agent's question: answered, or pending after timeout. It waits
        for a window to open when none is."""
        waiting = self._open(
            lambda id: Approval(
                id, origin, "Question", question, options=tuple(options),
                asked=wall_time(),
            )  # fmt: skip
        )
        return self.wait(waiting.approval.id, timeout)

    def wait(self, id: int, timeout: float = ANSWER_S) -> UserAnswer:
        with self._lock:
            waiting = self._waiting.get(id)
            answer = self._answers.get(id)
        if waiting is None and answer is None:
            raise LabError(ErrorCode.NOT_FOUND, f"No question {id}")
        if waiting is not None and not waiting.answered.wait(min(timeout, ANSWER_S)):
            return UserAnswer(id, pending=True)
        return UserAnswer(id, pending=False, answer=answer or waiting.answer)

    def answer(self, id: int, answer: Answer, confirm: str = "") -> None:
        """A person's answer; the first one closes it for every client."""
        with self._lock:
            waiting = self._waiting.get(id)
        if waiting is None:
            raise LabError(
                ErrorCode.NOT_FOUND, f"Nothing waits as {id}: answered or gone"
            )
        approval = waiting.approval
        if answer.allowed and approval.confirm and confirm != approval.confirm:
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"Type {approval.confirm} to allow this",
                approval.warning,
            )
        if answer.choice is not None and answer.choice not in approval.options:
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"{answer.choice!r} is not one of {list(approval.options)}",
            )
        self._close(waiting, answer)

    def pending(self) -> Tuple[Approval, ...]:
        with self._lock:
            return tuple(w.approval for w in self._waiting.values())

    def _open(self, approval: Callable[[int], Approval]) -> _Waiting:
        with self._lock:
            self._last += 1
            waiting = _Waiting(approval(self._last))
            self._waiting[self._last] = waiting
        self.events.publish(ApprovalRequested(waiting.approval))
        return waiting

    def _close(self, waiting: _Waiting, answer: Answer) -> Answer:
        """The answer it closes with: the first one, if two come at once."""
        id = waiting.approval.id
        with self._lock:
            if self._waiting.pop(id, None) is None:
                return waiting.answer
            waiting.answer = answer
            self._answers[id] = answer
            for old in list(self._answers)[: max(0, len(self._answers) - KEPT)]:
                del self._answers[old]
        waiting.answered.set()
        self.events.publish(ApprovalAnswered(id, answer))
        return answer
