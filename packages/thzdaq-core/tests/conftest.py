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
    from thzdaq_core.adapters.yaml_profiles import YamlProfiles, load_station
    from thzdaq_core.application.assembly import assemble
    from thzdaq_core.application.bench import Bench
    from thzdaq_core.application.lanes import Lanes
    from thzdaq_core.application.local import LocalLab
    from thzdaq_core.domain.station.station import Station

    profile = tmp_path / "bench.yaml"
    shutil.copy(PROFILE, profile)
    station = Station(load_station(profile), simulate=True)
    lanes = Lanes()
    bench = Bench(station, lanes, str(profile))
    assembled = assemble(bench, MeasurementStore(tmp_path / "data"), YamlProfiles())
    yield LocalLab(assembled, origin="test")
    assembled.close()
    lanes.stop()
    bench.station.close()
