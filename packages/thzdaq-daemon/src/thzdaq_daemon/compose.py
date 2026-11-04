"""The daemon's composition root: the station of a profile on the clock of this
process, the lanes of its instruments, the workspaces with a measurement store
each, and the use cases with the daemon's process as their DaemonControl."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_core.adapters.processes import Processes
from thzdaq_core.adapters.yaml_profiles import YamlProfiles, load_station
from thzdaq_core.application.assembly import Assembled, assemble
from thzdaq_core.application.bench import Bench
from thzdaq_api.lanes import Lanes
from thzdaq_core.application.ports import DaemonControl
from thzdaq_core.application.workspaces import Workspaces
from thzdaq_core.domain.station.config import StationConfig
from thzdaq_core.domain.station.station import Station

UNNAMED = "bench"  # the profile of a daemon started without one


@dataclass
class Composed:
    bench: Bench
    lanes: Lanes
    assembled: Assembled

    def close(self) -> None:
        self.assembled.close()
        self.lanes.stop()
        self.bench.station.close()


def compose(
    station: Optional[str],
    home: Path,
    data: Path,
    simulate: bool,
    control: DaemonControl,
    lively: bool = True,
) -> Composed:
    """station: a profile's file, or a name of home's stations/; home: the
    daemon's own workspace, its measurements in data; lively: simulators
    drift and get noisy as a bench does (tests keep exact values)."""
    workspaces = Workspaces(home, data, MeasurementStore)
    path = workspaces.profile(station) if station else None
    config = load_station(path) if path else StationConfig(UNNAMED)
    bench_station = Station(
        config, pause=time.sleep, simulate=simulate, lively=simulate and lively
    )
    lanes = Lanes()
    bench = Bench(bench_station, lanes, path)
    assembled = assemble(bench, workspaces, YamlProfiles(), control, Processes())
    return Composed(bench, lanes, assembled)
