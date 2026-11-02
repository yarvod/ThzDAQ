"""Who may do what: the origin of a call and the rights it needs give allow,
ask (a person allows it first) or deny.

People (the window, a CLI in their terminal) do what they ask: their clients
confirm dangerous steps themselves. Agents and scripts do what the daemon's
settings let them (thzdaq_api.rights.AGENTS until a person changes it), with
the rules nobody changes: they never change the profile or answer for a
person, and a call that may harm the bench (a dangerous step, a jump, a value
beyond the warn range, another's sweep) waits for a person even where they may
do it alone.
"""

from typing import Callable, Dict, Mapping

from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Rights
from thzdaq_api.origins import agent
from thzdaq_api.rights import AGENTS, FIXED, Decision

# Looking and stopping harm nothing: they are never asked for a risk
CALM = (Rights.READ, Rights.STOP)


class Policy:
    def __init__(self, settings: Callable[[], Mapping[Rights, Decision]]):
        """settings: what a person set for agents now (daemon.json)."""
        self.settings = settings

    def agents(self) -> Dict[Rights, Decision]:
        """What agents may do now, by every rights."""
        return {**AGENTS, **self.settings(), **FIXED}

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
        self, rights: Rights, origin: str, risky: Callable[[], bool]
    ) -> Decision:
        """risky: whether the call may harm the bench (asked only when an
        agent may otherwise do it alone)."""
        if not agent(origin):
            return Decision.ALLOW
        decision = self.agents()[rights]
        if decision is Decision.ALLOW and rights not in CALM and risky():
            return Decision.ASK
        return decision
