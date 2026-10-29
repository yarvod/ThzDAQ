"""Numbered events in a ring buffer.

Listeners hear each event in the thread that publishes it (a lane, the poll
scheduler), so they hand it on and return. A client that reconnects names the
last event it has and hears what it missed, or Resync when that is no longer
in the buffer.
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
        self._seq = 0

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
        for listener in listeners:
            listener(event)
        return event

    def subscribe(
        self, listener: Listener, since: Optional[int] = None
    ) -> Callable[[], None]:
        with self._lock:
            missed = [] if since is None else self._after(since)
            self._listeners.append(listener)
        for event in missed:
            listener(event)
        return lambda: self._unsubscribe(listener)

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
