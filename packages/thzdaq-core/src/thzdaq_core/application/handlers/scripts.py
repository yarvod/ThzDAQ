"""Operations on the scripts the daemon runs: start one, list them, read a
log, stop one."""

from typing import Tuple

from thzdaq_api import scripts as api

from thzdaq_core.application.approvals import Ask
from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.policy import Policy
from thzdaq_core.application.processes import ScriptProcesses

# Told to the person an agent's start is asked of
NOTHING_IN_ADVANCE = "an agent's --allow and --share allow nothing: it asks as it goes"


class StartScript(Handler[api.StartScript, api.ScriptInfo]):
    """A script has the rights of whoever starts it: an agent's start runs
    the agent's script, allowed nothing in advance."""

    operation = api.StartScript

    def __init__(self, scripts: ScriptProcesses, policy: Policy):
        self.scripts = scripts
        self.policy = policy

    def handle(self, args, origin):
        return self.scripts.start(args, origin, self.policy.agent(origin))

    def approval(self, args, origin):
        """The script and how it runs: what could not start is refused before
        anybody is asked."""
        self.scripts.check(args.allow)
        command = " ".join((*args.python, args.path, *args.arguments))
        given = args.allow or args.share
        told = (command, NOTHING_IN_ADVANCE if given else "")
        return Ask(f"Run script {args.path}", "; ".join(filter(None, told)))


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
