import time
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # lab_helpers

PROFILE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


@pytest.fixture
def lab(tmp_path):
    """The use cases of the simulated example bench (a copy of its profile),
    called as a client would."""
    from thzdaq_core.adapters.json_store import MeasurementStore
    from thzdaq_api.custom import LIBRARY
    from thzdaq_core.adapters.library import FolderLibrary
    from thzdaq_core.adapters.processes import Processes
    from thzdaq_core.adapters.yaml_profiles import YamlProfiles, load_station
    from thzdaq_core.application.assembly import assemble
    from thzdaq_core.application.bench import Bench
    from thzdaq_api.lanes import Lanes
    from thzdaq_core.application.local import LocalControl, LocalLab
    from thzdaq_api.measurements import DATA
    from thzdaq_core.application.workspaces import Workspaces
    from thzdaq_core.domain.station.station import Station

    profile = tmp_path / "bench.yaml"
    shutil.copy(PROFILE, profile)
    station = Station(load_station(profile), pause=time.sleep, simulate=True)
    lanes = Lanes()
    bench = Bench(station, lanes, str(profile))
    workspaces = Workspaces(tmp_path, tmp_path / DATA, MeasurementStore)
    assembled = assemble(
        bench, workspaces, YamlProfiles(), LocalControl(True), Processes(),
        FolderLibrary(tmp_path / LIBRARY),
    )  # fmt: skip
    yield LocalLab(assembled, origin="test", kind="test")
    assembled.close()
    lanes.stop()
    bench.station.close()


@pytest.fixture
def lab_as(lab):
    """The same bench called as another client: lab_as("gui"), lab_as("mcp:x");
    it listens as the kind its origin names unless given (lab_as("cli",
    "cli:answers")), as a main window when given its id (window=)."""
    from thzdaq_core.application.local import LocalLab

    return lambda origin, kind=None, window="": LocalLab(
        lab.assembled, origin, kind or origin.split(":")[0], window
    )
