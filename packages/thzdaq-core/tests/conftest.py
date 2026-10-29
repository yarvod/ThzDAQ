from pathlib import Path

import pytest

PROFILE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


@pytest.fixture
def lab():
    """The use cases of the simulated example bench, called as a client would."""
    from thzdaq_core.adapters.yaml_profiles import load_station
    from thzdaq_core.application.assembly import assemble
    from thzdaq_core.application.bench import Bench
    from thzdaq_core.application.lanes import Lanes
    from thzdaq_core.application.local import LocalLab
    from thzdaq_core.domain.station.station import Station

    station = Station(load_station(PROFILE), simulate=True)
    lanes = Lanes()
    yield LocalLab(assemble(Bench(station, lanes)), origin="test")
    lanes.stop()
    station.close()
