import gc
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
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
def freed(app):
    """Frees what a test deleted, after it (and when the test calls it), in
    the GUI thread: Qt deletes an object deleted outside of an event (a
    closed window, a session) only in an event loop, and the tests run none;
    then the collector frees the Python side of the deleted widgets
    (pyqtgraph's menus have no parent), held in cycles through their signals."""

    def free():
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    yield free
    free()


@pytest.fixture(autouse=True)
def exit_answer(monkeypatch):
    """Closing a window asks (layout, dump); tests answer Exit with the defaults.

    A test sets exit_answer["result"] or the checkbox states to answer otherwise.
    """
    from PySide6.QtWidgets import QDialog

    answer = {"result": QDialog.Accepted, "store": None, "dump": None, "stop": None}

    def exec_(dialog):
        for key, check in (
            ("store", dialog.storeState),
            ("dump", dialog.dumpData),
            ("stop", dialog.stopDaemon),
        ):
            if answer[key] is not None:
                check.setChecked(answer[key])
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
def bench(profile):
    """The simulated bench of the tests' lab: tests look at its instruments."""
    from thzdaq_api.lanes import Lanes
    from thzdaq_core.adapters.yaml_profiles import load_station
    from thzdaq_core.application.bench import Bench
    from thzdaq_core.domain.station.station import Station

    station = Station(
        load_station(profile), pause=time.sleep, simulate=True, lively=False
    )  # exact simulated values
    bench = Bench(station, Lanes(), str(profile))
    yield bench
    bench.lanes.stop()
    bench.station.close()


@pytest.fixture
def connect(bench, tmp_path):
    """What the session connects to: the bench's use cases in this process
    (LocalLab), called as the daemon serves them; it outlives a session, as a
    daemon outlives its window."""
    from thzdaq_api.measurements import DATA
    from thzdaq_core.adapters.json_store import MeasurementStore
    from thzdaq_api.custom import LIBRARY
    from thzdaq_core.adapters.library import FolderLibrary
    from thzdaq_core.adapters.processes import Processes
    from thzdaq_core.adapters.yaml_profiles import YamlProfiles
    from thzdaq_core.application.assembly import assemble
    from thzdaq_core.application.local import LocalControl, LocalLab
    from thzdaq_core.application.workspaces import Workspaces

    workspaces = Workspaces(tmp_path, tmp_path / DATA, MeasurementStore)
    assembled = assemble(
        bench, workspaces, YamlProfiles(), LocalControl(True), Processes(),
        FolderLibrary(tmp_path / LIBRARY),
    )  # fmt: skip
    yield lambda simulate: LocalLab(assembled, origin="gui", kind="gui")
    assembled.close()


@pytest.fixture
def new_session(app, tmp_path, connect):
    """Sessions of the program (started again after its window closed),
    shut down and deleted after the test."""
    from thzdaq_gui.session import Session

    made = []

    def started():
        session = Session(connect, tmp_path)
        session.open(True)
        made.append(session)
        return session

    yield started
    for session in made:
        session.shutdown()
        session.deleteLater()


@pytest.fixture
def session(new_session):
    return new_session()


@pytest.fixture
def window(session, tmp_path):
    from thzdaq_gui.main_window import MainWindow

    window = MainWindow(
        session,
        str(tmp_path / "settings.ini"),
        restore_layout=False,
        check_updates=False,
        mode="pro",  # the tests of docks per measurement and perspectives
    )
    window.show()
    yield window
    if window.isVisible():
        window.close()
