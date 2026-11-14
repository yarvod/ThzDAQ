"""Numbered events in a ring buffer.

Listeners hear each event in the thread that publishes it (a lane, the poll
scheduler), so they hand it on and return. A client that reconnects names the
last event it has and hears what it missed, or Resync when that is no longer
in the buffer. A stream to a client keeps only its place in the buffer and
waits for what comes after it (wait): the bus never waits for a client.
"""

import threading
from collections import deque
from typing import Callable, Deque, List, Optional

from thzdaq_api.events import Body, Event, Resync

from thzdaq_core.application.clock import wall_time

Listener = Callable[[Event], None]


class EventBus:
    def __init__(self, capacity: int = 10000):
        self._buffer: Deque[Event] = deque(maxlen=capacity)
        self._listeners: List[Listener] = []
        self._lock = threading.Lock()
        self._published = threading.Condition(self._lock)
        self._seq = 0
        self._woken = 0

    @property
    def seq(self) -> int:
        """Number of the last event published."""
        return self._seq

    def publish(self, body: Body) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(self._seq, wall_time(), body)
            self._buffer.append(event)
            listeners = list(self._listeners)
            self._published.notify_all()
        for listener in listeners:
            listener(event)
        return event

    def subscribe(
        self, listener: Listener, since: Optional[int] = None
    ) -> Callable[[], None]:
        """listener hears the events after since, then each as it is
        published. Another thread may publish while it is told what it
        missed: that event waits until it is told, so it hears them in order
        (it drops one older than what it heard, as a window does)."""
        turn = threading.RLock()  # re-entrant: a listener may publish
        turn.acquire()

        def ordered(event: Event) -> None:
            with turn:
                listener(event)

        try:
            with self._lock:
                missed = [] if since is None else self._after(since)
                self._listeners.append(ordered)
            for event in missed:
                listener(event)
        finally:
            turn.release()
        return lambda: self._unsubscribe(ordered)

    def wait(self, since: int, timeout: float) -> List[Event]:
        """The events after since, waiting up to timeout for one; Resync when
        since is no longer in the buffer."""
        with self._published:
            woken = self._woken
            self._published.wait_for(
                lambda: self._seq > since or self._woken != woken, timeout
            )
            return self._after(since)

    def wake(self) -> None:
        """Every wait returns at once (a server stops its streams)."""
        with self._published:
            self._woken += 1
            self._published.notify_all()

    def _after(self, since: int) -> List[Event]:
        if since >= self._seq:
            return []
        oldest = self._buffer[0].seq if self._buffer else self._seq + 1
        if since + 1 < oldest:
            return [Event(self._seq, wall_time(), Resync())]
        return [event for event in self._buffer if event.seq > since]

    def _unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)
