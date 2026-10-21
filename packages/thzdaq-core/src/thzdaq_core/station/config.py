"""Station (bench) profile: instruments and the roles measurements use.

An instrument is a driver plus its connection. A role names the part of an
instrument a measurement needs ("lo", "if_selector", "sis1"), optionally
wrapped by a port adapter (frequency multiplier, inverted switch, ...).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Hashable, List, Optional

from thzdaq_instruments.transport.base import ConnectionSpec

from thzdaq_core.errors import StationError

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass
class InstrumentConfig:
    driver: str  # registry key, e.g. "rigol.dp832a"
    connection: Optional[ConnectionSpec] = None
    options: Dict[str, Any] = field(default_factory=dict)  # driver constructor kwargs
    simulate: bool = False
    sim_options: Dict[str, Any] = field(default_factory=dict)  # simulator kwargs
    title: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)  # kept, not passed to driver


@dataclass
class RoleConfig:
    instrument: str  # instrument id in the station
    channel: Optional[Hashable] = None
    # Instrument method returning the part for `channel`: channel, ctrl, heater, ...
    accessor: str = "channel"
    adapter: Optional[str] = None  # port adapter name, see thzdaq_core.station.ports
    options: Dict[str, Any] = field(default_factory=dict)  # adapter kwargs
    attributes: Dict[str, Any] = field(default_factory=dict)  # set on the part
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StationConfig:
    name: str
    instruments: Dict[str, InstrumentConfig] = field(default_factory=dict)
    roles: Dict[str, RoleConfig] = field(default_factory=dict)
    description: str = ""

    def problems(self) -> List[str]:
        problems = []
        for instrument_id in self.instruments:
            if not IDENTIFIER.match(instrument_id):
                problems.append(f"instrument id {instrument_id!r} is not an identifier")
        for role, spec in self.roles.items():
            if not IDENTIFIER.match(role):
                problems.append(f"role {role!r} is not an identifier")
            if spec.instrument not in self.instruments:
                problems.append(
                    f"role {role!r} uses unknown instrument {spec.instrument!r}"
                )
        return problems

    def validate(self) -> "StationConfig":
        problems = self.problems()
        if problems:
            raise StationError(f"Station {self.name!r}: " + "; ".join(problems))
        return self
