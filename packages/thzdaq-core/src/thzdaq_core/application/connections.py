"""The bench lets go of connections it does not use: a TCP connection idle for a
while closes and the next command reopens it, so an R&S instrument leaves
remote mode and another program may connect. A measurement or a poll keeps its
connections busy, so they stay open."""

import threading

from thzdaq_core.application.bench import Bench

IDLE_S = 5.0  # a connection unused this long closes
LOOK_S = 1.0  # how often the idle ones are looked for


class IdleConnections:
    def __init__(self, bench: Bench, idle_s: float = IDLE_S):
        self.bench = bench
        self.idle_s = idle_s
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="idle connections", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped.wait(LOOK_S):
            # The station of now: another profile may have replaced it
            self.bench.station.close_idle_connections(self.idle_s)

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join(2.0)
