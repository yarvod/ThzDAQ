"""Operations on the daemon: its status, settings and log, a lane that hangs,
stopping and restarting it."""

from typing import Tuple

from thzdaq_api import daemon as api
from thzdaq_api.operation import Rights

from thzdaq_core.application.approvals import Ask
from thzdaq_core.application.daemon import DaemonService
from thzdaq_core.application.handlers import Handler


class GetDaemonStatus(Handler[api.GetDaemonStatus, api.DaemonStatus]):
    operation = api.GetDaemonStatus

    def __init__(self, daemon: DaemonService):
        self.daemon = daemon

    def handle(self, args, origin):
        return self.daemon.status()


class StopDaemon(Handler[api.StopDaemon, None]):
    operation = api.StopDaemon

    def __init__(self, daemon: DaemonService):
        self.daemon = daemon

    def handle(self, args, origin):
        self.daemon.stop(args.mode, origin)


class RestartDaemon(Handler[api.RestartDaemon, None]):
    operation = api.RestartDaemon

    def __init__(self, daemon: DaemonService):
        self.daemon = daemon

    def handle(self, args, origin):
        self.daemon.stop(args.mode, origin, restart=True)


class GetDaemonSettings(Handler[api.GetDaemonSettings, api.DaemonSettings]):
    operation = api.GetDaemonSettings

    def __init__(self, daemon: DaemonService):
        self.daemon = daemon

    def handle(self, args, origin):
        return self.daemon.settings()


class SetDaemonSettings(Handler[api.SetDaemonSettings, api.DaemonSettings]):
    operation = api.SetDaemonSettings

    def __init__(self, daemon: DaemonService):
        self.daemon = daemon

    def handle(self, args, origin):
        return self.daemon.change(args.idle_timeout, args.agents)

    def needs(self, args):
        """What agents may do is not theirs to change."""
        return Rights.STATION if args.agents else self.operation.rights

    def approval(self, args, origin):
        before = self.daemon.settings().idle_timeout
        after = before if args.idle_timeout is None else args.idle_timeout
        return Ask("Daemon settings", f"idle timeout {before:g} s → {after:g} s")


class ReadDaemonLog(Handler[api.ReadDaemonLog, Tuple[str, ...]]):
    operation = api.ReadDaemonLog

    def __init__(self, daemon: DaemonService):
        self.daemon = daemon

    def handle(self, args, origin):
        return self.daemon.log(args.lines)


class ResetLane(Handler[api.ResetLane, bool]):
    operation = api.ResetLane

    def __init__(self, daemon: DaemonService):
        self.daemon = daemon

    def handle(self, args, origin):
        return self.daemon.reset_lane(args.instrument)
