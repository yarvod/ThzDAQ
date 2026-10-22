import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"

# tests import EXAMPLE from here
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    # Settings go to a temporary INI file, never to the registry
    from thzdaq_gui import settings

    settings.use_file(tmp_path_factory.mktemp("settings") / "settings.ini")
    application = QApplication.instance() or QApplication([])
    from thzdaq_gui import theme

    theme.apply(application)
    return application


@pytest.fixture(autouse=True)
def exit_answer(monkeypatch):
    """Closing a window asks (layout, dump); tests answer Exit with the defaults.

    A test sets exit_answer["result"] or the checkbox states to answer otherwise.
    """
    from PySide6.QtWidgets import QDialog

    answer = {"result": QDialog.Accepted, "store": None, "dump": None}

    def exec_(dialog):
        if answer["store"] is not None:
            dialog.storeState.setChecked(answer["store"])
        if answer["dump"] is not None:
            dialog.dumpData.setChecked(answer["dump"])
        return answer["result"]

    monkeypatch.setattr("thzdaq_gui.exit_dialog.ExitDialog.exec", exec_)
    return answer


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
