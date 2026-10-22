import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"

# tests import EXAMPLE from here
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    # Personal preferences go to a temporary folder, never to the user's
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("prefs"))
    )
    application = QApplication.instance() or QApplication([])
    from thzdaq_gui import theme

    theme.apply(application)
    return application


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
def profile(tmp_path):
    """A copy of the 2SB example: tests that edit it save to the copy."""
    path = tmp_path / "bench.yaml"
    shutil.copy(EXAMPLE, path)
    return path


@pytest.fixture
def session(app, tmp_path, profile):
    from thzdaq_gui.session import Session

    session = Session(str(tmp_path / "data"))
    session.load_station(profile, simulate=True)
    yield session
    session.shutdown()


@pytest.fixture
def window(session, tmp_path):
    from thzdaq_gui.main_window import MainWindow

    window = MainWindow(
        session,
        str(tmp_path / "settings.ini"),
        restore_layout=False,
        check_updates=False,
    )
    window.show()
    yield window
    if window.isVisible():
        window.close()
