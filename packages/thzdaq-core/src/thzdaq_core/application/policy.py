"""Who may do what: the origin of a call and the rights it needs give allow,
ask (a person allows it first) or deny.

People (the window, a CLI in their terminal) do what they ask: their clients
confirm dangerous steps and raw writes themselves. Agents do what the daemon's
settings let them (thzdaq_api.rights.AGENTS until a person changes it), with
the rules nobody changes: agents never change the profile, answer for a person
or write raw commands. A script has the rights of whoever started it: a
script an agent started is the agent's, one a person started goes by
thzdaq_api.rights.PERSON_SCRIPTS. A call of an agent or a script that may harm
the bench (a dangerous step, a jump, a value beyond the warn range, another's
sweep) waits for a person even where it may do the call alone.

A call a person allowed already (granted: inside a script's session a person
allowed at its start, or what a person allowed a script at its start) is not
asked again, unless the person said agents may not do it at all.
"""

from typing import Callable, Dict, Mapping, Optional

from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Rights
from thzdaq_api.origins import agent, scripted
from thzdaq_api.rights import AGENTS, FIXED, PERSON_SCRIPTS, Decision

# Looking and stopping harm nothing: they are never asked for a risk
CALM = (Rights.READ, Rights.STOP)

# The origin of whoever started the script of an origin, as the daemon knows
# it (a script it runs); None: the daemon did not start it
Starter = Callable[[str], Optional[str]]


class Policy:
    def __init__(
        self,
        settings: Callable[[], Mapping[Rights, Decision]],
        starter: Starter = lambda origin: None,
    ):
        """settings: what a person set for agents now (daemon.json)."""
        self.settings = settings
        self.starter = starter

    def agents(self) -> Dict[Rights, Decision]:
        """What agents may do now, by every rights."""
        return {**AGENTS, **self.settings(), **FIXED}

    def agent(self, origin: str) -> bool:
        """An agent, or a script an agent started: by what the daemon knows
        of the scripts it runs, else by what the script calls itself."""
        by = self.starter(origin)
        return agent(origin) or (by is not None and self.agent(by))

    def of(self, origin: str) -> Dict[Rights, Decision]:
        """What an agent or a script may do now, by every rights."""
        if scripted(origin) and not self.agent(origin):
            return dict(PERSON_SCRIPTS)
        return self.agents()

    def changed(self, given: Mapping[Rights, Decision]) -> Dict[Rights, Decision]:
        """The table with what a person gives; LabError for a fixed one."""
        fixed = [r.value for r, d in given.items() if r in FIXED and d != FIXED[r]]
        if fixed:
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"{', '.join(fixed)} stay deny for agents",
                "agents never change the profile or answer for a person",
            )
        return {**self.agents(), **given}

    def decide(
        self,
        rights: Rights,
        origin: str,
        risky: Callable[[], bool],
        granted: Callable[[], bool] = lambda: False,
    ) -> Decision:
        """risky: whether the call may harm the bench (asked only when an
        agent or a script may otherwise do it alone); granted: a person
        allowed it already."""
        if not scripted(origin) and not self.agent(origin):
            return Decision.ALLOW
        decision = self.of(origin)[rights]
        if decision is Decision.ASK and granted():
            decision = Decision.ALLOW
        if decision is Decision.ALLOW and rights not in CALM and risky():
            return Decision.ASK
        return decision
