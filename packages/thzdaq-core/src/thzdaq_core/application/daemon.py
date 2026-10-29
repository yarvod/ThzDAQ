"""The daemon as the use cases see it: what it holds now, and how it ends.

Stopping with cancel or abort ends the measurements (their on_exit restores
what they changed) and then sets the profile's safe state; graceful is
refused while measurements run.
"""

from thzdaq_api.daemon import DaemonStatus, Heartbeat, LaneInfo, PollInfo, StopMode
from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.describe import connection_info
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.polling import Polling
from thzdaq_core.application.ports import DaemonControl
from thzdaq_core.application.runs import Runs

STUCK_S = 5.0  # a job running longer hangs: its device does not answer
END_S = 60.0  # how long stopping waits for measurements to restore what they changed


class DaemonService:
    def __init__(
        self,
        bench: Bench,
        runs: Runs,
        polling: Polling,
        events: EventBus,
        devices: DeviceAccess,
        control: DaemonControl,
    ):
        self.bench = bench
        self.runs = runs
        self.polling = polling
        self.events = events
        self.devices = devices
        self.control = control

    def status(self) -> DaemonStatus:
        station = self.bench.station
        lanes = tuple(
            LaneInfo(instrument, pending, label, busy, busy > STUCK_S)
            for instrument, pending, label, busy in self.bench.lanes.status()
        )
        connections = tuple(connection_info(c) for c in station.connections())
        problems = [
            f"{lane.instrument}: {lane.current or 'a job'} runs for {lane.busy_for:.0f} s"
            for lane in lanes
            if lane.stuck
        ] + [f"{c.label}: broken" for c in connections if c.broken]
        return DaemonStatus(
            process=self.control.process(),
            station=station.name,
            path=self.bench.path,
            opened=station.opened,
            clients=self.control.clients(),
            runs=self.runs.active(),
            lanes=lanes,
            connections=connections,
            polls=tuple(
                PollInfo(ref, interval, subscribers)
                for ref, (interval, _, subscribers) in self.polling.status().items()
            ),
            seq=self.events.seq,
            problems=tuple(problems),
        )

    def heartbeat(self, seq: int) -> Heartbeat:
        """The short news of a stream that heard up to seq."""
        status = self.status()
        return Heartbeat(seq, len(status.clients), len(status.runs), status.problems)

    def stop(self, mode: StopMode, origin: str, restart: bool = False) -> None:
        running = self.runs.active()
        if mode == StopMode.GRACEFUL:
            if running:
                titles = ", ".join(f"#{run.id} {run.title}" for run in running)
                raise LabError(
                    ErrorCode.CONFLICT,
                    f"Measurements run: {titles}",
                    "stop with cancel to end them, or wait for them",
                )
        else:
            if mode == StopMode.ABORT:
                for run in running:
                    self.runs.abort(run.id)
            self.runs.stop(END_S)
            self.devices.safe_state(origin, share=True)
        self.control.stop(restart)
