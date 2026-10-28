"""Where file dialogs start: the folder of the last file of each kind.

Every kind of file (measurements, station profiles) remembers in the settings
(folders/<kind>) the folder of the file chosen last. Until one is chosen, or
when it is gone (a removed USB stick), a dialog starts in the default of the
kind: the data folder of the session for measurements, so a data folder
chosen elsewhere moves where these dialogs start as well.
"""

from contextlib import suppress
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtWidgets import QFileDialog

from thzdaq_gui.settings import settings

MEASUREMENTS = "measurements"
PROFILES = "profiles"


class Folders:
    def __init__(self, defaults: Dict[str, Callable[[], Path]]):
        self.defaults = defaults  # kind -> its folder until one is chosen

    def folder(self, kind: str) -> Path:
        remembered = settings().value(f"folders/{kind}")
        if remembered and Path(remembered).is_dir():
            return Path(remembered)
        default = Path(self.defaults[kind]())
        with suppress(OSError):  # a dialog in a missing folder starts anywhere
            default.mkdir(parents=True, exist_ok=True)
        return default

    def remember(self, kind: str, path) -> None:
        settings().setValue(f"folders/{kind}", str(Path(path).resolve().parent))

    # Dialogs that start in the folder of the kind and remember the choice
    def save_path(
        self, parent, kind: str, title: str, name: str, filters: str
    ) -> Optional[Path]:
        path, _ = QFileDialog.getSaveFileName(
            parent, title, str(self.folder(kind) / name), filters
        )
        return self._chosen(kind, [path])[0] if path else None

    def open_path(self, parent, kind: str, title: str, filters: str) -> Optional[Path]:
        path, _ = QFileDialog.getOpenFileName(
            parent, title, str(self.folder(kind)), filters
        )
        return self._chosen(kind, [path])[0] if path else None

    def open_paths(self, parent, kind: str, title: str, filters: str) -> List[Path]:
        paths, _ = QFileDialog.getOpenFileNames(
            parent, title, str(self.folder(kind)), filters
        )
        return self._chosen(kind, paths)

    def _chosen(self, kind: str, paths: List[str]) -> List[Path]:
        if paths:
            self.remember(kind, paths[0])
        return [Path(path) for path in paths]
