"""What agents may do, by the rights a call needs: allow, ask (a person allows
it first) or deny. The daemon keeps the table in its settings; a person changes
it in the window (the Daemon dock) or with thzdaq daemon settings.

Some answers stay whatever the table says: agents never change the profile or
answer for a person, a dangerous step is always asked, and a set an agent may
do alone is still asked for a jump ×10 or a value beyond warn_min..warn_max.
"""

from enum import Enum
from typing import Mapping

from thzdaq_api.operation import Rights


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


# What agents may do until a person changes it
AGENTS: Mapping[Rights, Decision] = {
    Rights.READ: Decision.ALLOW,
    Rights.STOP: Decision.ALLOW,
    Rights.SET: Decision.ASK,
    Rights.RUN: Decision.ASK,
    Rights.DAEMON: Decision.ASK,
    Rights.STATION: Decision.DENY,
    Rights.ANSWER: Decision.DENY,
}

# What nobody changes: an agent could raise its own limits or rights, or
# stand for the person it asks
FIXED: Mapping[Rights, Decision] = {
    Rights.STATION: Decision.DENY,
    Rights.ANSWER: Decision.DENY,
}

# What a call of each rights does, for the person who chooses
MEANS: Mapping[Rights, str] = {
    Rights.READ: "look at devices, measurements and the daemon",
    Rights.SET: "set a quantity, run a device action",
    Rights.RUN: "start measurements, comment on them",
    Rights.STOP: "end measurements, bring devices to their safe state",
    Rights.DAEMON: "change the daemon's settings, stop or restart it",
    Rights.STATION: "change the profile and what agents may do",
    Rights.ANSWER: "answer for a person what waits for one",
}
