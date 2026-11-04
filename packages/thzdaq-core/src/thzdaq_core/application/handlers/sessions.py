"""Operations of a script's session: its start, its records, progress, plots,
what it restores at its end, and its end. Calls of the session's own script
were allowed with it (granted), but for a dangerous step."""

import msgspec
from thzdaq_api import sessions as api
from thzdaq_api.devices import QuantityValue

from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.scripts import Sessions, sweep_values


class _OfSession(Handler):
    """An operation of a session: its own script was allowed it at the start."""

    def __init__(self, sessions: Sessions):
        self.sessions = sessions

    def granted(self, args, origin):
        return self.sessions.owns(args.id, origin)


class StartSession(Handler[api.StartSession, api.RunInfo]):
    operation = api.StartSession

    def __init__(self, sessions: Sessions):
        self.sessions = sessions

    def handle(self, args, origin):
        return self.sessions.start(args, origin)

    def approval(self, args):
        return self.sessions.approval(args)

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


class RestoreOnExit(_OfSession):
    operation = api.RestoreOnExit

    def handle(self, args, origin):
        value = self.sessions.restore(args.id, origin, args.ref, args.key)
        return QuantityValue(args.ref, args.key, value)

    def granted(self, args, origin):
        return self.sessions.grants(args.id, origin, args.ref)

    def approval(self, args):
        return self.sessions.restore_ask(args.id, args.ref, args.key)


class CallOnExit(_OfSession):
    operation = api.CallOnExit

    def handle(self, args, origin):
        self.sessions.on_exit(args.id, origin, args.ref, args.action, args.arguments)

    def granted(self, args, origin):
        return self.sessions.grants(args.id, origin, args.ref)

    def approval(self, args):
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
