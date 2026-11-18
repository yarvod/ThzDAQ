"""Pictures of the dock for a person to look at, when asked for: a folder in
THZDAQ_SHOTS."""

import os
from pathlib import Path

SHOTS = os.environ.get("THZDAQ_SHOTS")


def shot(widget, name: str) -> None:
    if SHOTS:
        from PySide6.QtWidgets import QApplication

        for _ in range(3):  # the layout follows the messages' heights
            QApplication.processEvents()
        widget.grab().save(str(Path(SHOTS) / f"{name}.png"))
