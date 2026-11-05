"""What agents may do, by the rights a call needs: allow, ask (a person allows
it first) or deny. The daemon keeps the table in its settings; a person changes
it in the window (the Daemon dock) or with thzdaq daemon settings.

Some answers stay whatever the table says: agents never change the profile,
answer for a person or write raw commands, a dangerous step is always asked,
and a set an agent may do alone is still asked for a jump ×10 or a value
beyond warn_min..warn_max.

Scripts go by the same table, but for raw commands: they query an instrument
as people do, and a raw write waits for a person unless the script was
allowed it at its start (thzdaq script start --allow raw:<instrument>).
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
    Rights.RAW_QUERY: Decision.ASK,
    Rights.RAW_WRITE: Decision.DENY,
}

# What nobody changes: an agent could raise its own limits or rights, stand
# for the person it asks, or change an instrument past every limit
FIXED: Mapping[Rights, Decision] = {
    Rights.STATION: Decision.DENY,
    Rights.ANSWER: Decision.DENY,
    Rights.RAW_WRITE: Decision.DENY,
}

# What scripts may do whatever the table says for agents: a person wrote or
# started them for the bench, so a raw write is theirs to allow
SCRIPTS: Mapping[Rights, Decision] = {
    Rights.RAW_QUERY: Decision.ALLOW,
    Rights.RAW_WRITE: Decision.ASK,
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
    Rights.RAW_QUERY: "ask an instrument a raw command (with ?)",
    Rights.RAW_WRITE: "send an instrument a raw command that no limit checks",
}
