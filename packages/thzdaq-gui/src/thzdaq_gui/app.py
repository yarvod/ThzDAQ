"""The desktop application: a client of the bench daemon. It connects to the
daemon of the instruments (or of their simulator) and starts it when none
runs; closing the window leaves the daemon to its measurements. With --plot
it is only the plots window of one measurement (viewer.py)."""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from thzdaq_api import windows
from thzdaq_api.errors import LabError
from thzdaq_api.host import SIMULATE, connect_or_start
from thzdaq_api.origins import GUI
from thzdaq_api.workspace import NO_PROFILE, expected_profile, profile_path

from thzdaq_gui import theme, viewer
from thzdaq_gui.main_window import MainWindow
from thzdaq_gui.session import Session
from thzdaq_gui.settings import (
    STATION_PATH,
    app_dir,
    settings,
    stations_dir,
    use_file,
)
from thzdaq_gui.wording import STATION_PROFILE
from thzdaq_gui.workspace import default_workspace

DAEMON = "ThzDAQ daemon"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="thzdaq-gui", description="ThzDAQ desktop application"
    )
    parser.add_argument(
        "--station", help="station profile (YAML) to work with; the daemon loads it"
    )
    parser.add_argument(
        SIMULATE, action="store_true", help="work with the simulator's daemon"
    )
    parser.add_argument(
        windows.WORKSPACE,
        help="the folder whose data/ gets the measurements (default: the one "
        "made the default, else the program's)",
    )
    parser.add_argument(
        "--settings", help="keep settings in this INI file instead of the registry"
    )
    parser.add_argument(
        windows.PLOT, type=windows.which, metavar=windows.WHICH,
        help=f"only the plots of {windows.WHICH_HELP}",
    )  # fmt: skip
    windows.add_options(parser)
    parser.add_argument(
        "--quit-after", type=float, metavar="SECONDS", help=argparse.SUPPRESS
    )  # smoke test of a build
    args, qt_args = parser.parse_known_args(argv)

    if sys.platform == "win32":
        # Own taskbar button and icon, also when run from sources by python.exe
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ThzDAQ.ThzDAQ")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
    )
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    # Garbage collection only in the GUI thread, on a timer: a collection
    # started in a device or measurement thread may free Qt objects there
    from pyqtgraph.util.garbage_collector import GarbageCollector

    collector = GarbageCollector(interval=1.0)  # noqa: F841 (kept while running)
    app.setApplicationName("ThzDAQ")
    theme.apply(app)
    app.setWindowIcon(theme.app_icon())
    if args.plot is not None:
        return show_plots(app, args)
    if args.settings:
        use_file(args.settings)
    # Folders of an earlier update left in the system temp folder
    from thzdaq_gui.updates import clean_leftovers

    clean_leftovers()
    folder = Path(args.workspace) if args.workspace else default_workspace()
    station = start_profile(args.station, folder)
    session = Session(
        lambda simulate, origin=GUI, kind=GUI: connect_or_start(
            simulate, station, origin, kind
        ),
        folder,
    )
    # The lab comes first: its devices get docks the saved layout restores
    splash = QSplashScreen(theme.app_icon().pixmap(128, 128))
    splash.showMessage(
        "Connecting to the ThzDAQ daemon…", Qt.AlignBottom | Qt.AlignHCenter
    )
    splash.show()
    app.processEvents()
    try:
        session.open(args.simulate)
    except LabError as e:
        splash.close()
        QMessageBox.critical(None, DAEMON, f"{e.message}\n\n{e.hint}".strip())
        return 1
    window = MainWindow(session, check_updates=args.quit_after is None)
    window.show()
    splash.finish(window)
    if args.station:
        offer_profile(window, session, args.station)
    else:
        window.workspaceMenu.check_profile()
    if args.quit_after is not None:
        window.confirm_exit = False
        QTimer.singleShot(int(args.quit_after * 1000), window.close)
    return app.exec()


def show_plots(app: QApplication, args: argparse.Namespace) -> int:
    """Only the plots of one measurement, until the window is closed."""
    try:
        window = viewer.open_window(args.plot, args.simulate, windows.OwnPlot.of(args))
    except LabError as e:
        QMessageBox.critical(None, viewer.PROGRAM, f"{e.message}\n\n{e.hint}".strip())
        return 1
    window.show()
    if args.quit_after is not None:
        QTimer.singleShot(int(args.quit_after * 1000), window.close)
    return app.exec()


def start_profile(given: Optional[str], folder: Path) -> Optional[str]:
    """The profile a daemon this program starts loads: the one given, else the
    one the workspace expects, else the last one worked with, else
    stations/lab.yaml when it exists."""
    try:
        expected = expected_profile(folder)
    except LabError:  # a broken thzdaq.toml: the window tells it once open
        expected = None
    for candidate in (
        given,
        expected and profile_path(app_dir(), expected),
        settings().value(STATION_PATH),
        stations_dir() / "lab.yaml",
    ):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def offer_profile(window: MainWindow, session: Session, path: str) -> None:
    """The daemon already worked with another profile: switch only when asked."""
    loaded = session.profile().path
    if loaded is not None and Path(loaded).resolve() == Path(path).resolve():
        return
    answer = QMessageBox.question(
        window,
        STATION_PROFILE,
        f"The daemon works with {loaded or NO_PROFILE}. Switch it to {path}?",
    )
    if answer == QMessageBox.Yes:
        window.load_profile(path)
