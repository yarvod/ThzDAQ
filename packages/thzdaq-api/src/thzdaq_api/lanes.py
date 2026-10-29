"""Lanes: one thread and queue per key, an instrument in the daemon.

The jobs of one instrument run in order in its lane; instruments do not wait
for each other, so a slow or hung power meter does not hold the SIS bias.
Instruments sharing a connection (a Prologix) still take turns on its lock. A
client calls the daemon in lanes too: the calls about one device in order,
none waiting for a device that hangs.
"""

import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Called with (result, error) in the lane's thread when a job ends
Deliver = Callable[[Any, Optional[BaseException]], None]


class _Lane:
    def __init__(self, key: str):
        self.queue: "queue.Queue" = queue.Queue()
        self.started: Optional[float] = None
        self.label: Optional[str] = None
        name = f"lane {key}" if key else "lane"
        self.thread = threading.Thread(target=self.loop, name=name, daemon=True)
        self.thread.start()

    def loop(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            job, deliver, label = item
            self.label = label
            self.started = time.monotonic()
            try:
                result = job()
            except Exception as e:
                logger.exception(f"Device job failed{f' ({label})' if label else ''}")
                deliver(None, e)
            else:
                deliver(result, None)
            finally:
                self.started = None
                self.label = None
            # What deliver holds (GUI callbacks hold widgets) must not die here:
            # its last reference stays with whoever deliver handed it to
            del item, job, deliver
            result = None


class Lanes:
    def __init__(self):
        self._lanes: Dict[str, _Lane] = {}
        self._lock = threading.Lock()
        self._lane("")  # jobs without an instrument

    def _lane(self, key: str) -> _Lane:
        with self._lock:
            lane = self._lanes.get(key)
            if lane is None:
                lane = self._lanes[key] = _Lane(key)
            return lane

    def submit(
        self,
        key: str,
        job: Callable[[], Any],
        deliver: Deliver,
        label: Optional[str] = None,
    ) -> None:
        """key: the instrument whose lane the job joins; label: the device it
        talks to, named when it does not answer."""
        self._lane(key).queue.put((job, deliver, label))

    def call(
        self, key: str, job: Callable[[], Any], label: Optional[str] = None
    ) -> Any:
        """Run the job in its lane and wait for it; its error is raised here."""
        done = threading.Event()
        outcome: list = []

        def deliver(result, error):
            outcome.append((result, error))
            done.set()

        self.submit(key, job, deliver, label)
        done.wait()
        result, error = outcome[0]
        if error is not None:
            raise error
        return result

    def status(self) -> List[Tuple[str, int, Optional[str], float]]:
        """Each instrument's lane: (instrument, jobs waiting, the device the
        running job talks to, seconds it has run)."""
        now = time.monotonic()
        found = []
        for key, lane in list(self._lanes.items()):
            if not key:
                continue  # jobs of no instrument
            started, label = lane.started, lane.label  # the lane changes meanwhile
            busy = 0.0 if started is None else now - started
            found.append((key, lane.queue.qsize(), label, busy))
        return found

    @property
    def pending(self) -> int:
        return sum(lane.queue.qsize() for lane in list(self._lanes.values()))

    def _slowest(self) -> Tuple[Optional[float], Optional[str]]:
        """(start, label) of the longest job in progress; lanes change meanwhile."""
        busy = []
        for lane in list(self._lanes.values()):
            started, label = lane.started, lane.label
            if started is not None:
                busy.append((started, label))
        return min(busy, key=lambda item: item[0], default=(None, None))

    def busy_for(self) -> float:
        """Seconds the longest job in progress has been running (0 when idle)."""
        started, _ = self._slowest()
        return 0.0 if started is None else time.monotonic() - started

    @property
    def current(self) -> Optional[str]:
        """Label of the longest job in progress."""
        return self._slowest()[1]

    @property
    def started_at(self) -> Optional[float]:
        """When the longest job in progress started (monotonic), None when idle."""
        return self._slowest()[0]

    def stop(self, timeout: float = 2.0) -> None:
        lanes = list(self._lanes.values())
        for lane in lanes:
            lane.queue.put(None)
        deadline = time.monotonic() + timeout
        for lane in lanes:
            lane.thread.join(max(0.0, deadline - time.monotonic()))
