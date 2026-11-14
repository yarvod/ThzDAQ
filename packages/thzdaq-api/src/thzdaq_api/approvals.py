"""What waits for a person: an operation an agent may do only once a person
allows it, or a question an agent asks.

A person sees what will change ("sis_bias_1 · Voltage: 2.1 mV → 2.3 mV"),
may allow it with another value, or say no with words the agent reads.
The first person to answer closes it for every client (approval_answered).
"""

from typing import Optional, Tuple

import msgspec

from thzdaq_api.operation import Operation, Rights

# The longest a call waits for a person: less than an agent's tool timeout
ANSWER_S = 50.0


class Approval(msgspec.Struct, frozen=True):
    """What waits for a person. An operation has its name in operation; a
    question has none, and maybe options to choose from."""

    id: int
    origin: str  # who asks: mcp:<agent>, assistant, script:<name>
    title: str  # what: "sis_bias_1 · Voltage", "Start I-V curve"
    text: str  # how it changes, or the question
    warning: str = ""  # what may break (a dangerous step), a conflict
    confirm: str = ""  # typed by the person to allow a dangerous step
    value: Optional[str] = None  # the value asked for, in its unit: may be changed
    options: Tuple[str, ...] = ()  # a question's choices
    operation: str = ""
    asked: str = ""  # wall time, ISO


class Answer(msgspec.Struct, frozen=True):
    """A person's answer: allowed or not, with words for the agent."""

    allowed: bool
    text: str = ""  # why not, what to do instead; or a question's answer in words
    value: Optional[str] = None  # the value to set instead of the one asked for
    choice: Optional[str] = None  # one of a question's options
    by: str = ""  # who answered; "timeout" when nobody did


class UserAnswer(msgspec.Struct, frozen=True):
    """An agent's question: answered, or pending (wait_answer goes on)."""

    id: int
    pending: bool
    answer: Optional[Answer] = None


class ListApprovals(Operation[Tuple[Approval, ...]]):
    """What waits for a person now."""


class AnswerApproval(Operation[None]):
    """Answer what waits: allow it or not, with words for the agent. value
    allows an operation with another value (in its unit, "2.2 mV"); choice is
    one of a question's options; confirm repeats what a dangerous step asks to
    type. Only people answer, in the window or a terminal."""

    rights = Rights.ANSWER
    id: int
    allowed: bool
    text: str = ""
    value: Optional[str] = None
    choice: Optional[str] = None
    confirm: str = ""


class AskUser(Operation[UserAnswer]):
    """Ask the person at the bench and wait for the answer, at most timeout
    seconds (up to 50): a choice of options, words, or both. Still pending
    after that: wait_answer goes on waiting."""

    question: str
    options: Tuple[str, ...] = ()
    timeout: float = ANSWER_S


class WaitAnswer(Operation[UserAnswer]):
    """Wait for the answer to a question asked with ask_user, at most timeout
    seconds (up to 50)."""

    id: int
    timeout: float = ANSWER_S
