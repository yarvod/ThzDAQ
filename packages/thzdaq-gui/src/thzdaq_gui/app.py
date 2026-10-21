import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from thzdaq_instruments import InstrumentError

from thzdaq_gui.main_window import MainWindow
from thzdaq_gui.session import Session


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="thzdaq-gui", description="ThzDAQ desktop application"
    )
    parser.add_argument("--station", help="station profile (YAML) to open")
    parser.add_argument("--simulate", action="store_true", help="use simulators")
    parser.add_argument("--data", default="data", help="datasets folder")
    parser.add_argument(
        "--quit-after", type=float, metavar="SECONDS", help=argparse.SUPPRESS
    )  # smoke test of a build
    args, qt_args = parser.parse_known_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
    )
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("ThzDAQ")
    icon = resource_dir() / "assets" / "logo_small.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    session = Session(args.data)
    window = MainWindow(session, check_updates=args.quit_after is None)
    if args.station:
        try:
            session.load_station(args.station, args.simulate)
        except InstrumentError as e:
            QMessageBox.critical(window, "Station profile", str(e))
    window.show()
    if args.quit_after is not None:
        QTimer.singleShot(int(args.quit_after * 1000), window.close)
    return app.exec()


def resource_dir() -> Path:
    """Folder with bundled assets: the PyInstaller bundle or the working directory."""
    return Path(getattr(sys, "_MEIPASS", Path.cwd()))
