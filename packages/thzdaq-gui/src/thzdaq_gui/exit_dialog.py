"""Quit confirmation, as in the old app: keep the layout? dump the data? And
the daemon: it goes on after the window unless the person stops it."""

from datetime import datetime
from pathlib import Path
from typing import List

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)
from thzdaq_api.measurement_file import Measurement
from thzdaq_api.measurement_file import dumps

from thzdaq_gui import theme


def stop_by_default(running: int, others: int) -> bool:
    """Stop the daemon with the window when nothing else needs it."""
    return running == 0 and others == 0


class ExitDialog(QDialog):
    def __init__(
        self,
        running: int,
        measurements: int,
        others: int = 0,
        daemon: bool = True,
        parent=None,
    ):
        """running: measurements the daemon runs; others: its other clients
        (a window, a CLI); daemon: whether it answers."""
        super().__init__(parent)
        self.setWindowTitle("Exit")
        self.setWindowIcon(theme.icon("exit-run"))
        layout = QVBoxLayout(self)
        question = QLabel("Are you sure you want to exit?")
        question.setProperty("role", "title")
        layout.addWidget(question)
        if running:
            warning = QLabel(
                f"{running} measurement(s) run in the daemon: they go on unless "
                "the daemon is stopped."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet(f"color: {theme.ACCENT}")
            layout.addWidget(warning)
        self.storeState = QCheckBox(
            "Store the window layout and the current perspective"
        )
        self.storeState.setChecked(True)
        self.dumpData = QCheckBox(
            f"Dump all measurements of this session into one file ({measurements})"
        )
        self.dumpData.setChecked(measurements > 0)
        self.dumpData.setEnabled(measurements > 0)
        note = QLabel(
            "Every measurement is already saved to the data folder while it runs; "
            "the dump collects the session into one JSON file."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        self.stopDaemon = QCheckBox(
            "Stop the daemon: end its measurements, set the safe state"
            if running
            else "Stop the daemon"
        )
        self.stopDaemon.setChecked(daemon and stop_by_default(running, others))
        self.stopDaemon.setEnabled(daemon)
        if others:
            self.stopDaemon.setToolTip(f"{others} other client(s) work with it")
        for widget in (self.storeState, self.dumpData, note, self.stopDaemon):
            layout.addWidget(widget)
        buttons = QDialogButtonBox()
        buttons.addButton("Exit", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def dump_measurements(measurements: List[Measurement], root) -> Path:
    """All measurements in one file: <root>/dumps/dump_<date>_<time>.json."""
    folder = Path(root) / "dumps"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"dump_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    data = [m.to_dict() for m in measurements]
    path.write_text(dumps(data, indent=1), encoding="utf-8")
    return path
