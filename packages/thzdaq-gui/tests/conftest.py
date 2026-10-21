import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wait(app):
    def wait_until(predicate, timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("condition not reached in time")
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()

    return wait_until


@pytest.fixture
def session(app, tmp_path):
    from thzdaq_gui.session import Session

    session = Session(str(tmp_path / "data"))
    session.load_station(EXAMPLE, simulate=True)
    yield session
    session.shutdown()


# tests import EXAMPLE from here
import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
