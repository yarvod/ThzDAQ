"""Polling by subscription: one poll per device, at the shortest interval its
subscribers ask for, its readings published to all as values events. A poll
still waiting for its device is not queued again, so a slow instrument's lane
does not fill up."""

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from thzdaq_api.devices import Poll
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ReadFailed, Values

from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.events import EventBus


@dataclass
class _Device:
    interval: float
    keys: Optional[Tuple[str, ...]]  # None: every readable quantity
    next_at: float = 0.0
    busy: bool = False


@dataclass
class _Subscription:
    ref: str
    interval: float
    keys: Optional[Tuple[str, ...]] = field(default=None)


class Polling:
    def __init__(self, devices: DeviceAccess, events: EventBus):
        self.devices = devices
        self.events = events
        self._subscriptions: Dict[int, _Subscription] = {}
        self._polls: Dict[str, _Device] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="polling", daemon=True)
        self._thread.start()

    def subscribe(
        self, ref: str, interval: float, keys: Optional[Tuple[str, ...]] = None
    ) -> Poll:
        if interval <= 0:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, "interval must be above 0 s")
        self.devices.readable(ref, keys)  # unknown device or key: refused now
        with self._lock:
            poll_id = next(self._ids)
            self._subscriptions[poll_id] = _Subscription(ref, interval, keys)
            self._plan(ref)
        self._wake.set()
        return Poll(poll_id, ref, interval)

    def cancel(self, poll_id: int) -> None:
        with self._lock:
            subscription = self._subscriptions.pop(poll_id, None)
            if subscription is None:
                raise LabError(ErrorCode.NOT_FOUND, f"No poll {poll_id}")
            self._plan(subscription.ref)

    def status(self) -> Dict[str, Tuple[float, Optional[Tuple[str, ...]], int]]:
        """Each polled device: (interval, keys or None for all, subscriptions)."""
        with self._lock:
            return {
                ref: (
                    poll.interval,
                    poll.keys,
                    sum(1 for s in self._subscriptions.values() if s.ref == ref),
                )
                for ref, poll in self._polls.items()
            }

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()
        self._thread.join(2.0)

    def _plan(self, ref: str) -> None:
        """The device's poll from its subscriptions (under the lock)."""
        wanted = [s for s in self._subscriptions.values() if s.ref == ref]
        if not wanted:
            self._polls.pop(ref, None)
            return
        keys = None
        if all(s.keys is not None for s in wanted):
            keys = tuple(sorted({key for s in wanted for key in s.keys}))
        poll = self._polls.get(ref)
        interval = min(s.interval for s in wanted)
        if poll is None:
            self._polls[ref] = _Device(interval, keys)
        else:
            poll.interval, poll.keys = interval, keys

    def _loop(self) -> None:
        while not self._stopped.is_set():
            now = time.monotonic()
            with self._lock:
                due = [
                    (ref, poll.keys)
                    for ref, poll in self._polls.items()
                    if not poll.busy and poll.next_at <= now
                ]
                for ref, _ in due:
                    poll = self._polls[ref]
                    poll.busy, poll.next_at = True, now + poll.interval
                waits = [p.next_at - now for p in self._polls.values() if not p.busy]
            for ref, keys in due:
                self._read(ref, keys)
            self._wake.wait(max(0.005, min(waits, default=1.0)))
            self._wake.clear()

    def _read(self, ref: str, keys: Optional[Tuple[str, ...]]) -> None:
        def done(values, error):
            with self._lock:
                if ref in self._polls:
                    self._polls[ref].busy = False
            self._wake.set()
            if error is None:
                self.events.publish(Values(ref, values))
            else:
                self.events.publish(ReadFailed(ref, str(error)))

        try:
            self.devices.read_later(ref, keys, done)
        except LabError as e:  # the device left the profile
            done(None, e)
