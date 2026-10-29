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
        from thzdaq_core.application.lanes import Lanes
        from thzdaq_core.application.local import LocalControl
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
            MeasurementStore(tmp_path / "data"),
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
