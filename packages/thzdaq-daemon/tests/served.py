"""A daemon served in this process over HTTP, for the tests of its clients too
(the daemon's conftest and thzdaq-mcp's put this folder on the path)."""

import os
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path

PROFILE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


class Served:
    """A daemon served in this process over HTTP: what a test reaches inside it."""

    def __init__(self, tmp_path: Path):
        from thzdaq_api.daemon import API_VERSION, Health, HostInfo
        from thzdaq_core.adapters.json_store import MeasurementStore
        from thzdaq_core.adapters.processes import Processes
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
            Processes(),
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
