import shutil
import time
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


@pytest.fixture
def lab(tmp_path):
    """The simulated example bench's use cases in this process, as the daemon
    serves them (LocalLab)."""
    from thzdaq_api.lanes import Lanes
    from thzdaq_api.measurements import DATA
    from thzdaq_core.adapters.json_store import MeasurementStore
    from thzdaq_core.adapters.yaml_profiles import YamlProfiles, load_station
    from thzdaq_core.application.assembly import assemble
    from thzdaq_core.application.bench import Bench
    from thzdaq_core.application.local import LocalControl, LocalLab
    from thzdaq_core.application.workspaces import Workspaces
    from thzdaq_core.domain.station.station import Station

    profile = tmp_path / "bench.yaml"
    shutil.copy(EXAMPLE, profile)
    station = Station(
        load_station(profile), pause=time.sleep, simulate=True, lively=False
    )
    bench = Bench(station, Lanes(), str(profile))
    workspaces = Workspaces(tmp_path, tmp_path / DATA, MeasurementStore)
    assembled = assemble(bench, workspaces, YamlProfiles(), LocalControl(True))
    yield LocalLab(assembled, origin="cli")
    assembled.close()
    bench.lanes.stop()
    station.close()


@pytest.fixture
def thzdaq(lab, capsys, tmp_path, monkeypatch):
    """thzdaq ARGS on the lab, in tmp_path (the workspace of its runs): (exit
    code, stdout, stderr)."""
    from thzdaq_cli.app import main

    monkeypatch.chdir(tmp_path)

    def run(*argv):
        code = main(list(argv), connect=lambda simulate, autostart: lab)
        out, err = capsys.readouterr()
        return code, out, err

    return run
