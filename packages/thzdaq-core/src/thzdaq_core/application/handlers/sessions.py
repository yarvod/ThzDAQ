"""Operations of a script's session: its start, its records, progress, plots,
what it restores at its end, and its end. Calls of the session's own script
were allowed with it (granted), but for a dangerous step; a script the daemon
runs starts a session without asking when every device it names was allowed
to it in advance, and its sessions share what it was told to share."""

from typing import ClassVar

import msgspec
from thzdaq_api import sessions as api
from thzdaq_api.devices import QuantityValue
from thzdaq_api.scripts import CALL, SET

from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.processes import ScriptProcesses
from thzdaq_core.application.scripts import Sessions, sweep_values


class _OfSession(Handler):
    """An operation of a session: its own script was allowed it at the start."""

    def __init__(self, sessions: Sessions, scripts: ScriptProcesses):
        self.sessions = sessions
        self.scripts = scripts

    def granted(self, args, origin):
        return self.sessions.owns(args.id, origin)


class StartSession(_OfSession):
    operation = api.StartSession

    def handle(self, args, origin):
        shared = self._shared(args, origin)
        return self.sessions.start(shared, origin, self.scripts.noted(origin))

    def _shared(self, args, origin):
        """With the devices its script shares (thzdaq script start --share)."""
        shared = args.share + self.scripts.shared(origin)
        return msgspec.structs.replace(args, share=shared)

    def granted(self, args, origin):
        """Every device it names was allowed to its script in advance, or a
        session was made for it with a run that was allowed (the bench's own
        measurement)."""
        return self.sessions.adopting(origin) or self.scripts.allows_devices(
            origin, args.devices + args.exclusive
        )

    def approval(self, args, origin):
        return self.sessions.approval(self._shared(args, origin), origin)

    def amended(self, args, answer):
        """The sweeps the person saw are shared."""
        clashing = tuple(lease.device for lease in self.sessions.clashes(args))
        return msgspec.structs.replace(args, share=args.share + clashing)


class KeepSession(_OfSession):
    operation = api.KeepSession

    def handle(self, args, origin):
        return self.sessions.keep(args.id, origin, args.wait)


class RecordSession(_OfSession):
    operation = api.RecordSession

    def handle(self, args, origin):
        return self.sessions.record(
            args.id, origin, args.table, args.rows, args.columns
        )


class AdvanceSession(_OfSession):
    operation = api.AdvanceSession

    def handle(self, args, origin):
        return self.sessions.advance(args.id, origin, args.done, args.total)


class LogSession(_OfSession):
    operation = api.LogSession

    def handle(self, args, origin):
        self.sessions.log(args.id, origin, args.message)


class PlotSession(_OfSession):
    operation = api.PlotSession

    def handle(self, args, origin):
        return self.sessions.plot(args.id, origin, args.plot)


class _AtExit(_OfSession):
    """What the session does to a device at its end: allowed as the change it
    makes (kind: set or call), in the session or to its script in advance."""

    kind: ClassVar[str]

    def granted(self, args, origin):
        return self.sessions.grants(args.id, origin, args.ref) or self.scripts.allows(
            origin, self.kind, args.ref
        )


class RestoreOnExit(_AtExit):
    operation = api.RestoreOnExit
    kind = SET

    def handle(self, args, origin):
        value = self.sessions.restore(args.id, origin, args.ref, args.key)
        return QuantityValue(args.ref, args.key, value)

    def approval(self, args, origin):
        return self.sessions.restore_ask(args.id, args.ref, args.key)


class CallOnExit(_AtExit):
    operation = api.CallOnExit
    kind = CALL

    def handle(self, args, origin):
        self.sessions.on_exit(args.id, origin, args.ref, args.action, args.arguments)

    def approval(self, args, origin):
        return self.sessions.on_exit_ask(args.id, args.ref, args.action, args.arguments)


class EndSession(_OfSession):
    operation = api.EndSession

    def handle(self, args, origin):
        return self.sessions.end(
            args.id, origin, args.status, args.error, args.traceback
        )


class ParseSweep(Handler[api.ParseSweep, api.SweepValues]):
    operation = api.ParseSweep

    def handle(self, args, origin):
        return sweep_values(args.text, args.unit)
