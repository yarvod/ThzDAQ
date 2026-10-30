"""Who may do what: the origin of a call and the rights it needs give allow,
ask (a person allows it first) or deny.

People (the window, a CLI in their terminal) do what they ask: their clients
confirm dangerous steps themselves. Agents and scripts look and stop freely,
ask a person for anything that changes the bench, and never change the
profile or answer for a person.
"""

from enum import Enum
from typing import Mapping

from thzdaq_api.operation import Rights
from thzdaq_api.origins import agent


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


AGENTS: Mapping[Rights, Decision] = {
    Rights.READ: Decision.ALLOW,
    Rights.STOP: Decision.ALLOW,
    Rights.SET: Decision.ASK,
    Rights.RUN: Decision.ASK,
    Rights.DAEMON: Decision.ASK,
    Rights.STATION: Decision.DENY,
    Rights.ANSWER: Decision.DENY,
}


class Policy:
    def __init__(self, agents: Mapping[Rights, Decision] = AGENTS):
        self.agents = dict(agents)

    def decide(self, rights: Rights, origin: str) -> Decision:
        return self.agents[rights] if agent(origin) else Decision.ALLOW
