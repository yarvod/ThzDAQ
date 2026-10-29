"""The use cases of a bench, assembled: every handler with what it needs, listed
explicitly, and the services that run on their own (polling, letting idle
connections go) to stop at the end."""

from dataclasses import dataclass

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.connections import IdleConnections
from thzdaq_core.application.daemon import DaemonService
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.dispatch import Dispatcher
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.handlers import (
    analysis,
    daemon,
    devices,
    measurements,
    state,
    station,
)
from thzdaq_core.application.polling import Polling
from thzdaq_core.application.ports import DaemonControl, ProfileRepository
from thzdaq_core.application.runs import Runs
from thzdaq_core.application.station import StationService
from thzdaq_core.application.values import KnownValues
from thzdaq_core.application.workspaces import Workspaces
from thzdaq_core.domain.leases import Leases


@dataclass
class Assembled:
    dispatcher: Dispatcher
    events: EventBus
    polling: Polling
    runs: Runs
    daemon: DaemonService
    idle: IdleConnections

    def close(self) -> None:
        self.runs.stop()
        self.polling.stop()
        self.idle.stop()


def assemble(
    bench: Bench,
    workspaces: Workspaces,
    profiles: ProfileRepository,
    control: DaemonControl,
) -> Assembled:
    events = EventBus()
    known = KnownValues()
    runs = Runs(bench, workspaces, events, Leases(), known)
    access = DeviceAccess(bench, known, events, runs.leases, runs.note)
    polling = Polling(access, events)
    profile = StationService(bench, profiles, runs, events)
    service = DaemonService(bench, runs, polling, events, access, control)
    dispatcher = Dispatcher(
        (
            devices.ListDevices(bench),
            devices.DescribeDevice(bench, access),
            devices.ReadDevice(access),
            devices.SetQuantity(access),
            devices.CallAction(access),
            devices.SafeState(access),
            state.SubscribePoll(polling),
            state.CancelPoll(polling),
            state.GetSnapshot(events, known),
            state.ListLeases(runs),
            analysis.AnalyzeIv(),
            measurements.ListProcedures(),
            measurements.DescribeProcedure(access),
            measurements.StartMeasurement(runs),
            measurements.ListRuns(runs),
            measurements.WaitMeasurement(runs),
            measurements.CancelMeasurement(runs),
            measurements.AbortMeasurement(runs),
            measurements.SetComment(runs),
            station.GetStation(profile),
            station.LoadStation(profile),
            station.NewStation(profile),
            station.UpdateStation(profile),
            station.ListDrivers(profile),
            station.ListConnectionKinds(profile),
            station.ConnectInstrument(profile),
            station.GetSisCalibration(profile),
            station.SetSisCalibration(profile),
            station.ListConnections(profile),
            station.ResetConnection(profile),
            daemon.GetDaemonStatus(service),
            daemon.GetDaemonSettings(service),
            daemon.SetDaemonSettings(service),
            daemon.ReadDaemonLog(service),
            daemon.ResetLane(service),
            daemon.StopDaemon(service),
            daemon.RestartDaemon(service),
        )
    )
    return Assembled(dispatcher, events, polling, runs, service, IdleConnections(bench))
