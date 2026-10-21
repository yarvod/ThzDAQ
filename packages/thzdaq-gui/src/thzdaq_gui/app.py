import argparse
import logging
import sys
from typing import List, Optional

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
    args, qt_args = parser.parse_known_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
    )
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("ThzDAQ")
    session = Session(args.data)
    window = MainWindow(session)
    if args.station:
        try:
            session.load_station(args.station, args.simulate)
        except InstrumentError as e:
            QMessageBox.critical(window, "Station profile", str(e))
    window.show()
    return app.exec()
