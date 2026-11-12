import shutil
import sys
from pathlib import Path

import pytest

# The contract tests of core run here too, on RemoteLab (test_remote_contract.py)
CORE_TESTS = Path(__file__).parents[2] / "thzdaq-core" / "tests"
sys.path.insert(0, str(CORE_TESTS))  # lab_helpers and the test_lab_* modules
sys.path.insert(0, str(Path(__file__).parent))  # served

from served import PROFILE, Served  # noqa: E402


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
    it listens as the kind its origin names unless given, as a main window
    when given its id (window=)."""
    from thzdaq_api.remote import RemoteLab

    labs = []

    def remote(origin, kind=None, window=""):
        labs.append(
            RemoteLab(served.host, origin, kind or origin.split(":")[0], window=window)
        )
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


@pytest.fixture
def thzdaq(capsys, monkeypatch):
    """thzdaq ARGS against the simulator's daemon, as a person types it."""
    from thzdaq_api.origins import AGENT_SHELLS
    from thzdaq_cli.app import main

    for name in AGENT_SHELLS:
        monkeypatch.delenv(name, raising=False)

    def run(*argv):
        code = main(["--simulate", *argv])
        out, err = capsys.readouterr()
        return code, out, err

    return run
