import shutil
import time
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


@pytest.fixture(autouse=True)
def a_persons_terminal(monkeypatch):
    """Tests run as a person types, also from an agent's shell."""
    from thzdaq_api.origins import AGENT_SHELLS

    for name in AGENT_SHELLS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def lab(tmp_path):
    """The simulated example bench's use cases in this process, as the daemon
    serves them (LocalLab)."""
    from thzdaq_api.lanes import Lanes
    from thzdaq_api.measurements import DATA
    from thzdaq_core.adapters.json_store import MeasurementStore
    from thzdaq_core.adapters.processes import Processes
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
    assembled = assemble(
        bench, workspaces, YamlProfiles(), LocalControl(True), Processes()
    )
    yield LocalLab(assembled, origin="cli", kind="cli")
    assembled.close()
    bench.lanes.stop()
    station.close()


@pytest.fixture
def thzdaq(lab, capsys, tmp_path, monkeypatch):
    """thzdaq ARGS on the lab, in tmp_path (the workspace of its runs), as the
    lab's origin, listening as the command's kind: (exit code, stdout, stderr)."""
    from thzdaq_cli.app import main
    from thzdaq_core.application.local import LocalLab

    monkeypatch.chdir(tmp_path)

    def connect(simulate, autostart, kind):
        return LocalLab(lab.assembled, lab.origin, kind)

    def run(*argv):
        code = main(list(argv), connect=connect)
        out, err = capsys.readouterr()
        return code, out, err

    return run
