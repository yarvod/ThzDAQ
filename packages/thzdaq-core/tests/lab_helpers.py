"""Helpers of the tests that use the lab fixture (conftest puts this folder on the path)."""

import threading
import time

import msgspec
from thzdaq_api import wire
from thzdaq_api.approvals import AnswerApproval
from thzdaq_api.errors import LabError
from thzdaq_api.events import ApprovalAnswered, ApprovalRequested, UiRequested
from thzdaq_api.ui import AnswerUi


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "not reached in time"
        time.sleep(0.005)


def bodies(events, kind):
    """The bodies of the events of one kind, in order."""
    return [event.body for event in events if isinstance(event.body, kind)]


class Window:
    """A person's window: it listens to the daemon and answers what waits."""

    def __init__(self, lab):
        self.lab = lab
        self.heard = []
        self.stop = lab.subscribe(self.heard.append)

    def waiting(self):
        """What it heard asked and not yet answered."""
        answered = {body.id for body in bodies(self.heard, ApprovalAnswered)}
        return [
            body.approval
            for body in bodies(self.heard, ApprovalRequested)
            if body.approval.id not in answered
        ]

    def asked(self):
        """The newest request that waits, once it is heard."""
        wait_for(self.waiting)
        return self.waiting()[-1]

    def answer(self, **answer):
        self.lab.call(AnswerApproval(id=self.asked().id, **answer))

    def allow(self, count):
        """Allow what waits, one at a time, until count were: their titles."""
        titles = []
        while len(titles) < count:
            approval = self.asked()
            titles.append(approval.title)
            self.answer(allowed=True)
            wait_for(lambda: approval.id not in [a.id for a in self.waiting()])
        return titles


def calling(lab, operation):
    """The call in a thread: it waits for a person."""
    done = {}

    def call():
        try:
            done["result"] = lab.call(operation)
        except LabError as e:
            done["error"] = e

    thread = threading.Thread(target=call)
    thread.start()
    return thread, done


class Screen:
    """A main window as agents reach it: it listens with its id and answers
    what is asked of it (ui_requested) with shown(operation), in a thread of
    its own as a window does in its GUI thread. shown raises LabError to
    refuse."""

    def __init__(self, lab, shown=lambda operation: None):
        self.lab = lab
        self.shown = shown
        self.asked = []  # the operations asked of it
        self.stop = lab.subscribe(self._heard)

    def _heard(self, event):
        body = event.body
        if isinstance(body, UiRequested) and body.window == self.lab.window:
            threading.Thread(target=self._answer, args=(body,)).start()

    def _answer(self, body):
        operation = wire.decode_arguments(body.operation, wire.encode(body.arguments))
        self.asked.append(operation)
        try:
            result = msgspec.to_builtins(self.shown(operation))
        except LabError as e:
            self.lab.call(AnswerUi(id=body.id, failure=e.failure()))
        else:
            self.lab.call(AnswerUi(id=body.id, result=result))
