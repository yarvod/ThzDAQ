import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from thzdaq_instruments import InstrumentError

from thzdaq_gui import theme
from thzdaq_gui.main_window import MainWindow, settings_path
from thzdaq_gui.session import Session

DEFAULT_PROFILE = Path("stations") / "lab.yaml"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="thzdaq-gui", description="ThzDAQ desktop application"
    )
    parser.add_argument("--station", help="station profile (YAML) to open")
    parser.add_argument("--simulate", action="store_true", help="use simulators")
    parser.add_argument("--data", default="data", help="measurements folder")
    parser.add_argument("--settings", help="settings.ini with layout and perspectives")
    parser.add_argument(
        "--quit-after", type=float, metavar="SECONDS", help=argparse.SUPPRESS
    )  # smoke test of a build
    args, qt_args = parser.parse_known_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
    )
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("ThzDAQ")
    theme.apply(app)
    app.setWindowIcon(theme.icon("chip", theme.ACCENT))
    settings_file = args.settings or str(settings_path())
    session = Session(args.data)
    # The station comes first: its devices get docks the saved layout restores
    profile = args.station or QSettings(settings_file, QSettings.IniFormat).value(
        "station/path"
    )
    if not profile and DEFAULT_PROFILE.exists():
        profile = str(DEFAULT_PROFILE)
    problem = None
    if profile:
        try:
            session.load_station(profile, args.simulate)
        except (InstrumentError, OSError) as e:
            problem = str(e)
    window = MainWindow(session, settings_file, check_updates=args.quit_after is None)
    window.show()
    if problem:
        QMessageBox.critical(window, "Station profile", problem)
    if args.quit_after is not None:
        QTimer.singleShot(int(args.quit_after * 1000), window.close)
    return app.exec()


def resource_dir() -> Path:
    """Folder with bundled assets: the PyInstaller bundle or the working directory."""
    return Path(getattr(sys, "_MEIPASS", Path.cwd()))
