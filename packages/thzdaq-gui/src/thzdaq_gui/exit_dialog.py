"""Quit confirmation, as in the old app: keep the layout? dump the data?"""

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
from thzdaq_core.data.measurement import Measurement
from thzdaq_core.data.store import dumps

from thzdaq_gui import theme


class ExitDialog(QDialog):
    def __init__(self, running: int, measurements: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exit")
        self.setWindowIcon(theme.icon("exit-run"))
        layout = QVBoxLayout(self)
        question = QLabel("Are you sure you want to exit?")
        question.setProperty("role", "title")
        layout.addWidget(question)
        if running:
            warning = QLabel(
                f"{running} measurement(s) are running and will be stopped."
            )
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
        for widget in (self.storeState, self.dumpData, note):
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
