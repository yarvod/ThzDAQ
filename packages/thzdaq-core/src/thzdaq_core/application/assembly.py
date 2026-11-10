"""The use cases of a bench, assembled: every handler with what it needs, listed
explicitly, and the services that run on their own (polling, letting idle
connections go) to stop at the end."""

from dataclasses import dataclass

from thzdaq_api.host import script_python
from thzdaq_api.origins import answers

from thzdaq_core.application.approvals import Approvals
from thzdaq_core.application.bench import Bench
from thzdaq_core.application.check import Checks
from thzdaq_core.application.connections import IdleConnections
from thzdaq_core.application.custom import CustomMeasurements, CustomRuns
from thzdaq_core.application.daemon import DaemonService
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.dispatch import Dispatcher
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.handlers import (
    analysis,
    approvals,
    custom,
    daemon,
    devices,
    measurements,
    scripts,
    sessions,
    state,
    station,
)
from thzdaq_core.application.policy import Policy
from thzdaq_core.application.polling import Polling
from thzdaq_core.application.ports import (
    DaemonControl,
    Launcher,
    Library,
    ProfileRepository,
)
from thzdaq_core.application.procedures import Procedures
from thzdaq_core.application.processes import ScriptProcesses
from thzdaq_core.application.runs import Runs
from thzdaq_core.application.scripts import Sessions
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
    control: DaemonControl
    scripts: ScriptProcesses
    customs: CustomMeasurements

    def close(self) -> None:
        self.customs.stop()
        self.scripts.stop_all()
        self.runs.stop()
        self.polling.stop()
        self.idle.stop()


def assemble(
    bench: Bench,
    workspaces: Workspaces,
    profiles: ProfileRepository,
    control: DaemonControl,
    launcher: Launcher,
    library: Library,
) -> Assembled:
    """launcher: how scripts the daemon runs are started (adapters.processes);
    library: the bench's own measurements (adapters.library)."""
    events = EventBus()
    known = KnownValues()
    runs = Runs(bench, workspaces, events, Leases(), known, profiles)
    access = DeviceAccess(bench, known, events, runs.leases, runs.note)
    script_sessions = Sessions(runs, access)
    customs = CustomMeasurements(library, events)
    procedures = Procedures(customs)
    processes = ScriptProcesses(
        bench, workspaces, runs, events, script_sessions, launcher,
        lambda: control.process().simulate, procedures.get,
    )  # fmt: skip
    custom_runs = CustomRuns(customs, processes, script_sessions, script_python)
    checks = Checks(customs, bench, access)
    polling = Polling(access, events)
    profile = StationService(bench, profiles, runs, events, workspaces)
    policy = Policy(lambda: control.settings().agents, processes.started_by)
    service = DaemonService(
        bench, runs, polling, events, access, control, policy, processes
    )
    # A person answers in a window or a terminal that listens to the daemon
    waiting = Approvals(
        events, lambda: any(answers(c.kind, c.origin) for c in control.clients())
    )
    dispatcher = Dispatcher(
        (
            devices.ListDevices(bench),
            devices.DescribeDevice(bench, access),
            devices.ReadDevice(access, script_sessions),
            devices.SetQuantity(access, script_sessions, processes),
            devices.CallAction(access, script_sessions, processes),
            devices.RawCommand(access, script_sessions, processes),
            devices.SafeState(access),
            state.SubscribePoll(polling),
            state.CancelPoll(polling),
            state.GetSnapshot(events, known),
            state.ListLeases(runs),
            analysis.AnalyzeIv(),
            approvals.ListApprovals(waiting),
            approvals.AnswerApproval(waiting),
            approvals.AskUser(waiting),
            approvals.WaitAnswer(waiting),
            measurements.ListProcedures(procedures),
            measurements.DescribeProcedure(access, procedures),
            measurements.StartMeasurement(
                runs, processes, procedures, custom_runs, policy
            ),
            measurements.ListRuns(runs),
            measurements.GetRunSnapshot(runs),
            measurements.WaitMeasurement(runs),
            measurements.SummarizeMeasurement(runs),
            measurements.CancelMeasurement(runs),
            measurements.AbortMeasurement(runs),
            measurements.SetComment(runs),
            sessions.StartSession(script_sessions, processes),
            sessions.KeepSession(script_sessions, processes),
            sessions.RecordSession(script_sessions, processes),
            sessions.AdvanceSession(script_sessions, processes),
            sessions.LogSession(script_sessions, processes),
            sessions.PlotSession(script_sessions, processes),
            sessions.RestoreOnExit(script_sessions, processes),
            sessions.CallOnExit(script_sessions, processes),
            sessions.EndSession(script_sessions, processes),
            sessions.ParseSweep(),
            custom.ParseValue(),
            custom.ListCustom(customs),
            custom.ReadCustom(customs),
            custom.CheckCustom(checks),
            custom.WriteCustom(customs, checks),
            scripts.StartScript(processes, policy),
            scripts.ListScripts(processes),
            scripts.ReadScriptLog(processes),
            scripts.StopScript(processes),
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
        ),
        policy,
        waiting,
    )
    customs.start()
    return Assembled(
        dispatcher, events, polling, runs, service, IdleConnections(bench), control,
        processes, customs,
    )  # fmt: skip
