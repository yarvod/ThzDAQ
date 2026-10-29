"""The use cases of a bench, assembled: every handler with what it needs, listed
explicitly, and the services that run on their own (polling) to stop at the end."""

from dataclasses import dataclass

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.dispatch import Dispatcher
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.handlers import (
    analysis,
    devices,
    measurements,
    state,
    station,
)
from thzdaq_core.application.polling import Polling
from thzdaq_core.application.ports import MeasurementRepository, ProfileRepository
from thzdaq_core.application.runs import Runs
from thzdaq_core.application.station import StationService
from thzdaq_core.application.values import KnownValues
from thzdaq_core.domain.leases import Leases


@dataclass
class Assembled:
    dispatcher: Dispatcher
    events: EventBus
    polling: Polling
    runs: Runs

    def close(self) -> None:
        self.runs.stop()
        self.polling.stop()


def assemble(
    bench: Bench, store: MeasurementRepository, profiles: ProfileRepository
) -> Assembled:
    events = EventBus()
    known = KnownValues()
    runs = Runs(bench, store, events, Leases())
    access = DeviceAccess(bench, known, events, runs.leases, runs.note)
    polling = Polling(access, events)
    profile = StationService(bench, profiles, runs, events)
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
            measurements.DescribeProcedure(),
            measurements.StartMeasurement(runs),
            measurements.ListRuns(runs),
            measurements.WaitMeasurement(runs),
            measurements.CancelMeasurement(runs),
            measurements.AbortMeasurement(runs),
            station.GetStation(profile),
            station.LoadStation(profile),
            station.NewStation(profile),
            station.UpdateStation(profile),
            station.ListDrivers(profile),
            station.ListConnections(profile),
            station.ResetConnection(profile),
        )
    )
    return Assembled(dispatcher, events, polling, runs)
