"""Operations on the daemon: its status, stopping and restarting it."""

from thzdaq_api import daemon as api

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
