"""Helpers of the tests that use the lab fixture (conftest puts this folder on the path)."""

import threading
import time

from thzdaq_api.approvals import AnswerApproval
from thzdaq_api.errors import LabError
from thzdaq_api.events import ApprovalAnswered, ApprovalRequested


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
