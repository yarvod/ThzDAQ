"""The daemon as the use cases see it: what it holds now, and how it ends.

Stopping with cancel or abort ends the scripts and measurements (their
on_exit restores what they changed) and then sets the profile's safe state;
graceful is refused while they run.
"""

from typing import Mapping, Optional, Tuple

import msgspec
from thzdaq_api.daemon import (
    DaemonSettings,
    DaemonStatus,
    Heartbeat,
    LaneInfo,
    PollInfo,
    StopMode,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Rights
from thzdaq_api.rights import Decision

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.describe import connection_info
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.policy import Policy
from thzdaq_core.application.polling import Polling
from thzdaq_core.application.ports import DaemonControl
from thzdaq_core.application.processes import ScriptProcesses
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
        policy: Policy,
        scripts: ScriptProcesses,
        stuck: float = STUCK_S,
    ):
        """stuck: seconds after which a running job hangs."""
        self.bench = bench
        self.scripts = scripts
        self.runs = runs
        self.polling = polling
        self.events = events
        self.devices = devices
        self.control = control
        self.policy = policy
        self.stuck = stuck

    def status(self) -> DaemonStatus:
        station = self.bench.station
        lanes = tuple(
            LaneInfo(instrument, pending, label, busy, busy > self.stuck)
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
            scripts=self.scripts.running(),
        )

    def heartbeat(self, seq: int) -> Heartbeat:
        """The short news of a stream that heard up to seq."""
        status = self.status()
        return Heartbeat(seq, len(status.clients), len(status.runs), status.problems)

    def settings(self) -> DaemonSettings:
        """As kept, with what agents may do by every rights."""
        kept = self.control.settings()
        return msgspec.structs.replace(kept, agents=self.policy.agents())

    def change(
        self, idle_timeout: Optional[float], agents: Mapping[Rights, Decision]
    ) -> DaemonSettings:
        """What is given changes, the rest stays."""
        if idle_timeout is not None and idle_timeout < 0:
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS, "idle_timeout is 0 (never) or more s"
            )
        kept = self.control.settings()
        self.control.change(
            DaemonSettings(
                kept.idle_timeout if idle_timeout is None else idle_timeout,
                self.policy.changed(agents),
            )
        )
        return self.settings()

    def log(self, lines: int) -> Tuple[str, ...]:
        if lines <= 0:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, "lines must be above 0")
        return self.control.log(lines)

    def reset_lane(self, instrument: str) -> bool:
        """Break the commands of an instrument that hangs and give it a new
        lane; the calls waiting in the old one fail."""
        self.bench.instrument(instrument)  # an unknown one is NOT_FOUND
        station = self.bench.station
        station.abort([d.ref for d in station.devices() if d.instrument == instrument])
        return self.bench.lanes.reset(instrument)

    def stop(self, mode: StopMode, origin: str, restart: bool = False) -> None:
        running = self.runs.active()
        if mode == StopMode.GRACEFUL:
            busy = [f"#{run.id} {run.title}" for run in running] + [
                f"script {script.id} {script.name}" for script in self.scripts.running()
            ]
            if busy:
                raise LabError(
                    ErrorCode.CONFLICT,
                    f"Measurements or scripts run: {', '.join(busy)}",
                    "stop with cancel to end them, or wait for them",
                )
        else:
            self.scripts.stop_all()
            if mode == StopMode.ABORT:
                for run in running:
                    self.runs.abort(run.id)
            self.runs.stop(END_S)
            self.devices.safe_state(origin, share=True)
        self.control.stop(restart)
