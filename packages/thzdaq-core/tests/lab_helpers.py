"""Helpers of the tests that use the lab fixture (conftest puts this folder on the path)."""

import time


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "not reached in time"
        time.sleep(0.005)


def bodies(events, kind):
    """The bodies of the events of one kind, in order."""
    return [event.body for event in events if isinstance(event.body, kind)]
