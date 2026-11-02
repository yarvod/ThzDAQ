import os
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

# The contract tests of core run here too, on RemoteLab (test_remote_contract.py)
CORE_TESTS = Path(__file__).parents[2] / "thzdaq-core" / "tests"
sys.path.insert(0, str(CORE_TESTS))  # lab_helpers and the test_lab_* modules

PROFILE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


class Served:
    """A daemon served in this process over HTTP: what a test reaches inside it."""

    def __init__(self, tmp_path: Path):
        from thzdaq_api.daemon import API_VERSION, Health, HostInfo
        from thzdaq_core.adapters.json_store import MeasurementStore
        from thzdaq_core.adapters.yaml_profiles import YamlProfiles, load_station
        from thzdaq_core.application.assembly import assemble
        from thzdaq_core.application.bench import Bench
        from thzdaq_api.lanes import Lanes
        from thzdaq_core.application.local import LocalControl
        from thzdaq_api.measurements import DATA
        from thzdaq_core.application.workspaces import Workspaces
        from thzdaq_core.domain.station.station import Station
        from thzdaq_daemon.server import Clients, Server

        class ServedControl(LocalControl):
            """Its clients are the server's listeners, as in the daemon."""

            def clients(control):
                return self.clients.all()

        self.clients = Clients()
        profile = tmp_path / "bench.yaml"
        shutil.copy(PROFILE, profile)
        station = Station(load_station(profile), pause=time.sleep, simulate=True)
        self.lanes = Lanes()
        self.bench = Bench(station, self.lanes, str(profile))
        self.assembled = assemble(
            self.bench,
            Workspaces(tmp_path, tmp_path / DATA, MeasurementStore),
            YamlProfiles(),
            ServedControl(True),
        )
        self.server = Server(
            self.assembled.dispatcher,
            self.assembled.events,
            self.assembled.daemon,
            secrets.token_urlsafe(16),
            Health(os.getpid(), API_VERSION, "test", True),
            self.clients,
        )
        threading.Thread(
            target=self.server.serve_forever, args=(0.02,), daemon=True
        ).start()  # a short poll: the server stops at once after each test
        self.host = HostInfo(
            os.getpid(), self.server.port, self.server.token, API_VERSION, "test",
            sys.executable, "", str(profile), True,
        )  # fmt: skip

    def close(self) -> None:
        self.server.stop()
        self.assembled.close()
        self.lanes.stop()
        self.bench.station.close()


@pytest.fixture
def served(tmp_path):
    served = Served(tmp_path)
    yield served
    served.close()


@pytest.fixture
def lab(served):
    """The core contract tests' lab: RemoteLab to a daemon in this process."""
    from thzdaq_api.remote import RemoteLab

    class ServedLab(RemoteLab):
        """Tests that look inside the bench reach its use cases, as with LocalLab."""

        def __init__(self):
            super().__init__(served.host, origin="test", kind="test")
            self.assembled = served.assembled
            self.dispatcher = served.assembled.dispatcher

    remote = ServedLab()
    yield remote
    remote.close()


@pytest.fixture
def lab_as(served):
    """The served daemon called as another client: lab_as("gui"), lab_as("mcp:x");
    it listens as the kind its origin names unless given."""
    from thzdaq_api.remote import RemoteLab

    labs = []

    def remote(origin, kind=None):
        labs.append(RemoteLab(served.host, origin, kind or origin.split(":")[0]))
        return labs[-1]

    yield remote
    for opened in labs:
        opened.close()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A daemon's folder with the example profile; its files live there too,
    apart from any daemon of the machine, and its daemons end with the test."""
    from thzdaq_api.host import NO_AUTOSTART_ENV, kill

    monkeypatch.setenv("THZDAQ_DAEMON_DIR", str(tmp_path))
    monkeypatch.delenv(NO_AUTOSTART_ENV, raising=False)
    shutil.copy(PROFILE, tmp_path / "bench.yaml")
    yield tmp_path
    for simulate in (True, False):
        kill(simulate)
