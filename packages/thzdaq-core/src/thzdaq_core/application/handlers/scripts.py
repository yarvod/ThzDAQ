"""Operations on the scripts the daemon runs: start one, list them, read a
log, stop one."""

from typing import Tuple

from thzdaq_api import scripts as api

from thzdaq_core.application.approvals import Ask
from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.processes import ScriptProcesses


class StartScript(Handler[api.StartScript, api.ScriptInfo]):
    operation = api.StartScript

    def __init__(self, scripts: ScriptProcesses):
        self.scripts = scripts

    def handle(self, args, origin):
        return self.scripts.start(args, origin)

    def approval(self, args, origin):
        """The script, how it runs and what it may do without asking: what
        could not start is refused before anybody is asked."""
        self.scripts.check(args.allow)
        command = " ".join((*args.python, args.path, *args.arguments))
        allowed = ", ".join(str(grant) for grant in args.allow)
        given = (
            command,
            f"may {allowed} without asking" if allowed else "",
            f"shares {', '.join(args.share)}" if args.share else "",
        )
        return Ask(f"Run script {args.path}", "; ".join(filter(None, given)))


class ListScripts(Handler[api.ListScripts, Tuple[api.ScriptInfo, ...]]):
    operation = api.ListScripts

    def __init__(self, scripts: ScriptProcesses):
        self.scripts = scripts

    def handle(self, args, origin):
        return self.scripts.all()


class ReadScriptLog(Handler[api.ReadScriptLog, api.ScriptLog]):
    operation = api.ReadScriptLog

    def __init__(self, scripts: ScriptProcesses):
        self.scripts = scripts

    def handle(self, args, origin):
        return self.scripts.log(args.id, args.since)


class StopScript(Handler[api.StopScript, api.ScriptInfo]):
    operation = api.StopScript

    def __init__(self, scripts: ScriptProcesses):
        self.scripts = scripts

    def handle(self, args, origin):
        return self.scripts.stop(args.id)
