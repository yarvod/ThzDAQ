import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from thzdaq_instruments import InstrumentError

from thzdaq_gui import theme
from thzdaq_gui.main_window import MainWindow
from thzdaq_gui.session import Session
from thzdaq_gui.settings import data_dir, settings, stations_dir, use_file


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="thzdaq-gui", description="ThzDAQ desktop application"
    )
    parser.add_argument("--station", help="station profile (YAML) to open")
    parser.add_argument("--simulate", action="store_true", help="use simulators")
    parser.add_argument(
        "--data", help="measurements folder (default: data next to the program)"
    )
    parser.add_argument(
        "--settings", help="keep settings in this INI file instead of the registry"
    )
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
    if args.settings:
        use_file(args.settings)
    # Folders of an earlier update left in the system temp folder
    from thzdaq_gui.updates import clean_leftovers

    clean_leftovers()
    session = Session(args.data or str(data_dir()))
    # The station comes first: its devices get docks the saved layout restores
    profile = args.station or settings().value("station/path")
    if profile and not Path(profile).exists():
        profile = None
    default = stations_dir() / "lab.yaml"
    if not profile and default.exists():
        profile = str(default)
    problem = None
    if profile:
        try:
            session.load_station(profile, args.simulate)
        except (InstrumentError, OSError) as e:
            problem = str(e)
    window = MainWindow(session, check_updates=args.quit_after is None)
    window.show()
    lock = instance_lock()
    if lock is None and args.quit_after is None:
        QMessageBox.warning(
            window,
            "ThzDAQ is already running",
            "Another ThzDAQ (a build or a run from sources) is open. Instruments "
            "with one connection (Prologix, R&S supplies) can serve only one of "
            "them: close the other before working with the instruments.",
        )
    if problem:
        QMessageBox.critical(window, "Station profile", problem)
    if args.quit_after is not None:
        window.confirm_exit = False
        QTimer.singleShot(int(args.quit_after * 1000), window.close)
    return app.exec()


_locks = []


def instance_lock(path: Optional[Path] = None) -> Optional[QLockFile]:
    """A lock shared by builds and runs from sources; None when another holds it."""
    if path is None:
        temp = QStandardPaths.writableLocation(QStandardPaths.TempLocation)
        path = Path(temp) / "thzdaq.lock"
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)  # held for hours; staleness is by the owner's PID
    if not lock.tryLock(100):
        return None
    _locks.append(lock)  # held until the process ends
    return lock
